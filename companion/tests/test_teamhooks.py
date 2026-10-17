import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from forever_notify import cli, config, setup_wizard, teamhooks

URL = "https://discord.com/api/webhooks/123456789/secret-token"
HOOKS = {"kill": URL + "/kills", "pvp": URL + "/pvp", "flag": URL + "/pvp"}


class Encryption(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)

    def test_round_trip_and_no_plain_text(self):
        blob = teamhooks.encode(URL, {"kill": URL + "/kills"}, self.key)
        self.assertNotIn(b"discord", blob)
        self.assertNotIn(b"secret-token", blob)
        self.assertEqual(teamhooks.decode(blob, self.key), (URL, {"kill": URL + "/kills"}))

    def test_each_seal_differs(self):
        self.assertNotEqual(teamhooks.seal(b"same", self.key), teamhooks.seal(b"same", self.key))

    def test_tampering_and_wrong_key_rejected(self):
        blob = bytearray(teamhooks.encode(URL, {}, self.key))
        with self.assertRaises(teamhooks.TeamHooksError):
            teamhooks.decode(bytes(blob), os.urandom(32))
        blob[30] ^= 1
        with self.assertRaises(teamhooks.TeamHooksError):
            teamhooks.decode(bytes(blob), self.key)
        with self.assertRaises(teamhooks.TeamHooksError):
            teamhooks.unseal(b"junk", self.key)


class TeamCode(unittest.TestCase):
    def test_round_trip_hides_urls_and_survives_chat_wrapping(self):
        code = teamhooks.make_code(URL, HOOKS)
        self.assertTrue(code.startswith(teamhooks.CODE_PREFIX))
        self.assertNotIn("discord", code.lower())
        self.assertLess(len(code), 2000, "fits in one Discord message")
        self.assertEqual(teamhooks.read_code(code), (URL, HOOKS))
        wrapped = f"`{code[:50]}\n {code[50:120]} {code[120:]}`"
        self.assertEqual(teamhooks.read_code(wrapped), (URL, HOOKS))

    def test_bad_codes_rejected(self):
        code = teamhooks.make_code(URL, HOOKS)
        for bad in ("", URL, code[:-10], code[:40] + ("A" if code[40] != "A" else "B") + code[41:]):
            with self.assertRaises(teamhooks.TeamHooksError, msg=bad[:30]):
                teamhooks.read_code(bad)

    def test_no_webhooks_in_the_code_base(self):
        package = Path(teamhooks.__file__).parent
        self.assertFalse((package / "team_data.py").exists())


class TeamSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.wow = self.tmp / "World of Warcraft" / "_forever_"
        (self.wow / "WTF").mkdir(parents=True)
        self.path = self.tmp / "config.toml"

    def test_setup_with_team_code_retries_a_bad_paste(self):
        answers = iter(["1", "FNTEAM1-garbage", teamhooks.make_code(URL, HOOKS), "1"])
        with redirect_stdout(io.StringIO()):
            setup_wizard.run(self.path, ask=lambda _: next(answers), candidates=[self.wow],
                             install_addon=lambda _: True)
        cfg = config.load(self.path)
        self.assertEqual(cfg.webhook_for("death"), URL)
        self.assertEqual(cfg.webhook_for("kill"), URL + "/kills")
        self.assertEqual(cfg.webhook_for("flag"), URL + "/pvp")
        self.assertEqual(cfg.screenshots_dir, self.wow / "Screenshots")

    def test_old_config_without_webhooks_asks_for_the_code_and_keeps_settings(self):
        # A config.toml written by a version with the team's webhooks built in.
        template = setup_wizard.resource_path("config.example.toml").read_text(encoding="utf-8")
        text = re.sub(r"(?m)^flag = true", "flag = false", setup_wizard.render_config(template, "", str(self.wow)))
        self.path.write_text(text, encoding="utf-8")
        with self.assertRaises(config.NoWebhookError):
            config.load(self.path)

        answers = iter(["1", teamhooks.make_code(URL, HOOKS)])
        with redirect_stdout(io.StringIO()):
            setup_wizard.add_webhooks(self.path, ask=lambda _: next(answers))
        cfg = config.load(self.path)
        self.assertEqual(cfg.webhook_for("level"), URL)
        self.assertEqual(cfg.webhook_for("kill"), URL + "/kills")
        self.assertEqual(cfg.wow_dir, self.wow)
        self.assertFalse(cfg.enabled("flag"), "other settings kept")

    def test_run_asks_for_webhooks_when_config_has_none(self):
        template = setup_wizard.resource_path("config.example.toml").read_text(encoding="utf-8")
        self.path.write_text(setup_wizard.render_config(template, "", str(self.wow)), encoding="utf-8")
        answers = iter(["1", teamhooks.make_code(URL, HOOKS)])
        add_webhooks = setup_wizard.add_webhooks
        tty = mock.Mock(isatty=lambda: True)
        with mock.patch.object(cli.setup_wizard, "add_webhooks",
                               lambda path: add_webhooks(path, ask=lambda _: next(answers))), \
                mock.patch.object(cli.sys, "stdin", tty), \
                mock.patch.object(cli, "send_tests", return_value=True) as send_tests, \
                mock.patch.object(cli.addon_install, "sync_and_report"), mock.patch.object(cli.app, "run"), \
                redirect_stdout(io.StringIO()):
            code = cli.main(["-c", str(self.path), "run"])
        self.assertEqual(code, 0)
        send_tests.assert_called_once()  # samples posted, like after setup
        self.assertEqual(config.load(self.path).webhook_for("kill"), URL + "/kills")


if __name__ == "__main__":
    unittest.main()
