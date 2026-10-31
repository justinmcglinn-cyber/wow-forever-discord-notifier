import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from forever_notify import cli, config, setup_wizard, teamhooks

EXAMPLE = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text(encoding="utf-8")
HOOK = "https://discord.com/api/webhooks/{}/token"
OLD = {event: HOOK.format(n) for n, event in enumerate(("death", "level", "pvp", "kill", "summary"), 1)}


def answers(*items):
    it = iter(items)
    return lambda _prompt: next(it)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old_wow = self.tmp / "old" / "_forever_"
        self.new_wow = self.tmp / "new" / "_forever_"
        for wow in (self.old_wow, self.new_wow):
            (wow / "WTF").mkdir(parents=True)
        self.path = self.tmp / "config.toml"
        text = setup_wizard.render_config(EXAMPLE, "", str(self.old_wow), OLD)
        text = setup_wizard.set_value(text, "notify", "pvp_flag", "false")
        text = setup_wizard.set_value(text, "mentions", "pvp_alerts", "'<@42>'")
        self.path.write_text(text, encoding="utf-8")

    def load(self):
        return config.load(self.path)


class ResetChannels(Base):
    def test_team_code_replaces_every_old_channel_and_keeps_other_settings(self):
        team = HOOK.format(99)
        code = teamhooks.make_code(team, {})
        with redirect_stdout(io.StringIO()):
            setup_wizard.reset_channels(self.path, answers("1", code))
        cfg = self.load()
        for event, _ in setup_wizard.CHANNELS:
            self.assertEqual(cfg.webhook_for(event), team, event)  # no stale per-channel webhook left
        self.assertFalse(cfg.enabled("flag"))
        self.assertEqual(cfg.pvp_mention, "<@42>")
        self.assertEqual(cfg.screenshots_dir, self.old_wow / "Screenshots")

    def test_one_channel(self):
        with redirect_stdout(io.StringIO()):
            setup_wizard.reset_channels(self.path, answers("2", "not a url", HOOK.format(7)))
        self.assertEqual({self.load().webhook_for(e) for e, _ in setup_wizard.CHANNELS}, {HOOK.format(7)})

    def test_reset_posts_a_sample_to_each_new_channel(self):
        with mock.patch.object(cli.discord, "post", return_value=None) as post, redirect_stdout(io.StringIO()):
            cli.reset(self.path, "channels", ask=answers("2", HOOK.format(7)))
        self.assertEqual({call.args[0] for call in post.call_args_list}, {HOOK.format(7)})
        self.assertEqual(post.call_count, len(setup_wizard.CHANNELS))


class ResetWowFolder(Base):
    def test_changes_only_the_folder_and_installs_the_addon(self):
        installed = []
        with redirect_stdout(io.StringIO()):
            setup_wizard.reset_wow_folder(self.path, answers("2"), candidates=[self.old_wow, self.new_wow],
                                          install_addon=installed.append)
        cfg = self.load()
        self.assertEqual(cfg.screenshots_dir, self.new_wow / "Screenshots")
        self.assertEqual(cfg.webhook_for("kill"), OLD["kill"])
        self.assertEqual(installed, [self.new_wow])

    def test_path_overrides_for_the_old_folder_are_removed(self):
        text = "wow_dir = 'C:\\old'\nscreenshots_dir = 'D:\\old\\Screenshots'\n\n[webhooks]\ndefault = ''\n"
        out, removed = setup_wizard.set_wow_dir(text, r"E:\new")
        self.assertEqual(removed, ["screenshots_dir"])
        self.assertTrue(out.startswith("wow_dir = 'E:\\new'\n"))
        self.assertNotIn("screenshots_dir", out)
        self.assertIn("[webhooks]\ndefault = ''", out)

    def test_adds_folder_when_missing(self):
        out, _ = setup_wizard.set_wow_dir("[webhooks]\ndefault = ''\n", r"E:\new")
        self.assertTrue(out.startswith("wow_dir = 'E:\\new'\n[webhooks]"))


class FakeConsole:
    """Stands in for msvcrt: keys pressed in the console window."""

    def __init__(self, keys):
        self.keys = list(keys)

    def kbhit(self):
        return bool(self.keys)

    def getwch(self):
        return self.keys.pop(0)


class KeysWhileRunning(Base):
    def make_keys(self):
        self.now, self.said = 0.0, []
        keys = cli.ResetKeys(enabled=True, show=lambda: self.said.append("open"),
                             closed=lambda: self.said.append("closed"), clock=lambda: self.now)
        keys.enabled = True  # as on Windows
        return keys

    def press(self, keys, *chars):
        with mock.patch.dict(sys.modules, {"msvcrt": FakeConsole(chars)}):
            return keys()

    def test_only_c_and_w_pause_watching_while_the_shortcuts_are_open(self):
        keys = self.make_keys()
        keys.open()
        self.assertTrue(self.press(keys, "x", "\xe0", "H", "W"))  # the arrow key's H isn't taken as a key
        self.assertEqual(keys.pressed, "wow_folder")
        self.assertFalse(keys.is_open)  # the question closes them
        self.assertFalse(self.press(keys, "q", "1"))

    def test_shortcuts_close_after_a_while_and_space_opens_them(self):
        keys = self.make_keys()
        keys.open()
        self.now = cli.SHORTCUTS_SECONDS
        self.assertFalse(self.press(keys, "c"))  # closed: a stray C does nothing
        self.assertIsNone(keys.pressed)
        self.assertEqual(self.said, ["open", "closed"])
        self.assertTrue(self.press(keys, " ", "c"))
        self.assertEqual(keys.pressed, "channels")
        self.assertEqual(self.said, ["open", "closed", "open"])

    def test_esc_closes_the_shortcuts(self):
        keys = self.make_keys()
        keys.open()
        self.assertFalse(self.press(keys, "\x1b", "w", "\x1b"))
        self.assertIsNone(keys.pressed)
        self.assertEqual(self.said, ["open", "closed"])  # a second Esc says nothing

    def test_disabled_without_a_console(self):
        self.assertFalse(cli.ResetKeys(enabled=False)())

    def test_pressing_w_while_running_changes_folder_and_keeps_watching(self):
        runs = []

        def fake_run(cfg, send, stop):
            runs.append(cfg.screenshots_dir)
            if len(runs) == 1:
                with mock.patch.dict(sys.modules, {"msvcrt": FakeConsole(["w"])}):
                    self.assertTrue(stop())  # the player presses W
            # second run: returns as if the window were closed

        args = types.SimpleNamespace(config=self.path, dry_run=True)
        with mock.patch.object(cli, "_interactive", return_value=True), \
                mock.patch.object(cli.sys, "platform", "win32"), \
                mock.patch.object(cli.app, "run", fake_run), \
                mock.patch.object(cli.addon_install, "sync_and_report"), \
                mock.patch.object(cli.addon_install, "install_and_report", return_value=True), \
                mock.patch.object(setup_wizard, "find_wow_dirs", return_value=[self.old_wow, self.new_wow]), \
                mock.patch("sys.stdin", io.StringIO("2\n")), redirect_stdout(io.StringIO()) as out:
            code = cli._watch(args, self.load(), None, [])
        self.assertEqual(code, 0)
        self.assertEqual(runs, [self.old_wow / "Screenshots", self.new_wow / "Screenshots"])
        self.assertIn("[C] Change Discord channels   [W] Change WoW folder", out.getvalue())  # no colour: plain


class Commands(Base):
    def test_reset_wow_folder_command(self):
        with mock.patch.object(setup_wizard, "find_wow_dirs", return_value=[self.new_wow]), \
                mock.patch.object(setup_wizard.addon_install, "install_and_report", return_value=True), \
                mock.patch("sys.stdin", io.StringIO("1\n")), redirect_stdout(io.StringIO()):
            code = cli.main(["-c", str(self.path), "reset-wow-folder"])
        self.assertEqual(code, 0)
        self.assertEqual(self.load().screenshots_dir, self.new_wow / "Screenshots")

    def test_reset_without_config_points_to_normal_start(self):
        with redirect_stdout(io.StringIO()) as out:
            code = cli.main(["-c", str(self.tmp / "missing.toml"), "reset-channels"])
        self.assertEqual(code, 2)
        self.assertIn("start ForeverNotify normally", out.getvalue())


if __name__ == "__main__":
    unittest.main()
