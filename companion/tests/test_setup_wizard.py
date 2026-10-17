import io
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unittest import mock

from forever_notify import addon_install, cli, config, setup_wizard

WEBHOOK = "https://discord.com/api/webhooks/123/abc"


class SetupWizard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.wow = self.tmp / "World of Warcraft" / "_forever_"
        (self.wow / "WTF").mkdir(parents=True)

    def run_wizard(self, answers, candidates):
        answers = iter(answers)
        path = self.tmp / "config.toml"
        self.installed_to = []
        with redirect_stdout(io.StringIO()):
            setup_wizard.run(path, ask=lambda _: next(answers), candidates=candidates,
                             install_addon=self.installed_to.append)
        return config.load(path)

    def test_one_channel_picks_detected_folder_and_rejects_bad_webhook(self):
        cfg = self.run_wizard(["4", "2", "not a url", WEBHOOK, "1"], [self.wow])
        self.assertEqual(cfg.webhook_url, WEBHOOK)
        self.assertEqual(cfg.webhooks, {})
        self.assertEqual(cfg.screenshots_dir, self.wow / "Screenshots")
        self.assertEqual(cfg.wow_dir, self.wow)
        self.assertEqual(self.installed_to, [self.wow])
        self.assertTrue(cfg.notify["pvp"])

    def test_separate_channels(self):
        gold, deaths, level, pvp, kills = (f"{WEBHOOK}/{n}" for n in ("gold", "deaths", "level", "pvp", "kills"))
        cfg = self.run_wizard(["3", deaths, level, pvp, kills, gold, "1"], [self.wow])
        text = (self.tmp / "config.toml").read_text(encoding="utf-8")
        for name, url in [("deaths", deaths), ("level_ups", level), ("pvp_alerts", pvp), ("pvp_kills", kills),
                          ("gold_summary", gold)]:
            self.assertIn(f"\n{name} = '{url}'", text)
        for event, url in [("death", deaths), ("level", level), ("pvp", pvp), ("flag", pvp), ("kill", kills),
                           ("summary", gold)]:
            self.assertEqual(cfg.webhook_for(event), url, event)

    def test_separate_channels_enter_reuses_previous(self):
        other = WEBHOOK + "/other"
        cfg = self.run_wizard(["3", WEBHOOK, "", other, "", "", "1"], [self.wow])
        self.assertEqual(cfg.webhook_for("level"), WEBHOOK)
        self.assertEqual(cfg.webhook_for("summary"), other)
        self.assertEqual(cfg.webhooks, {"death": WEBHOOK, "level": WEBHOOK, "pvp": other, "kill": other,
                                        "summary": other})
        self.assertEqual(cfg.webhook_for("flag"), other)

    def test_pasted_path_with_quotes_and_apostrophe(self):
        odd = self.tmp / "Bob's Games" / "_forever_"
        odd.mkdir(parents=True)
        cfg = self.run_wizard(["2", WEBHOOK, str(self.tmp / "missing"), f'"{odd}"'], [])
        self.assertEqual(cfg.screenshots_dir, odd / "Screenshots")

    def test_find_wow_dirs(self):
        (self.tmp / "World of Warcraft" / "_retail_").mkdir()
        self.assertEqual(setup_wizard.find_wow_dirs([str(self.tmp)]), [self.wow])


class AddonInstall(unittest.TestCase):
    def setUp(self):
        self.wow = Path(tempfile.mkdtemp())
        self.target = addon_install.installed_addon(self.wow)

    def test_bundled_addon_found_from_source(self):
        self.assertTrue((addon_install.bundled_addon() / "ForeverNotify.toc").is_file())

    def test_install_update_and_status(self):
        self.assertEqual(addon_install.status(self.wow), "missing")
        addon_install.install(self.wow)
        self.assertEqual(self.target, self.wow / "Interface" / "AddOns" / "ForeverNotify")
        self.assertEqual(addon_install.status(self.wow), "current")

        (self.target / "Core.lua").write_text("-- old version", encoding="utf-8")
        (self.target / "Stale.lua").write_text("-- removed file", encoding="utf-8")
        self.assertEqual(addon_install.status(self.wow), "outdated")
        addon_install.install(self.wow)
        self.assertEqual(addon_install.status(self.wow), "current")
        self.assertFalse((self.target / "Stale.lua").exists())

    def set_installed_version(self, version):
        toc = self.target / "ForeverNotify.toc"
        text = toc.read_text(encoding="utf-8")
        toc.write_text(re.sub(r"(?m)^## Version: .*$", f"## Version: {version}", text), encoding="utf-8")

    def test_sync(self):
        bundled = addon_install.toc_version(addon_install.bundled_addon())
        self.assertIsNotNone(bundled)
        self.assertEqual(addon_install.sync(self.wow), "installed")
        self.assertEqual(addon_install.sync(self.wow), "current")

        self.set_installed_version("0.0.1")  # older: replaced
        self.assertEqual(addon_install.sync(self.wow), "updated")
        self.assertEqual(addon_install.status(self.wow), "current")

        (self.target / "Core.lua").write_text("-- edited", encoding="utf-8")  # same version, different files
        self.assertEqual(addon_install.sync(self.wow), "updated")

        self.set_installed_version("999.0")  # newer: kept
        self.assertEqual(addon_install.sync(self.wow), "kept-newer")
        self.assertEqual(addon_install.toc_version(self.target), (999, 0))

    def test_missing_bundle(self):
        missing_source = self.wow / "nothing"
        with self.assertRaises(FileNotFoundError):
            addon_install.install(self.wow, source=missing_source)
        self.assertEqual(addon_install.status(self.wow, source=missing_source), "unknown")


EXAMPLE = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text(encoding="utf-8")


WOW = r"C:\WoW"


class SetWebhook(unittest.TestCase):
    def write_config(self, webhooks=None):
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text(setup_wizard.render_config(EXAMPLE, WEBHOOK, WOW, webhooks), encoding="utf-8")
        return path

    def test_sets_one_channel_keeping_comments_and_others(self):
        text = setup_wizard.render_config(EXAMPLE, WEBHOOK, WOW, {"pvp": WEBHOOK + "/pvp"})
        out = setup_wizard.set_webhook(text, "kill", WEBHOOK + "/kills")
        # only that value changes; its comment stays
        self.assertEqual(out, text.replace('pvp_kills = ""', "pvp_kills = '" + WEBHOOK + "/kills'"))
        self.assertIn("pvp_kills = '" + WEBHOOK + "/kills'      # 🗡️", out)
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text(out, encoding="utf-8")
        cfg = config.load(path)
        self.assertEqual(cfg.webhook_for("kill"), WEBHOOK + "/kills")
        self.assertEqual(cfg.webhook_for("pvp"), WEBHOOK + "/pvp")
        self.assertEqual(cfg.webhook_for("death"), WEBHOOK)

    def test_replaces_existing_line_and_old_name(self):
        text = setup_wizard.render_config(EXAMPLE, WEBHOOK, WOW, {"kill": WEBHOOK + "/old"})
        out = setup_wizard.set_webhook(text, "kill", WEBHOOK + "/new")
        self.assertNotIn("/old", out)
        self.assertEqual(out.count("pvp_kills = '"), 1)
        old = setup_wizard.set_webhook("wow_dir = 'y'\n[webhooks]\nkill = 'https://old'\n", "kill", WEBHOOK)
        self.assertEqual(old, "wow_dir = 'y'\n[webhooks]\npvp_kills = '" + WEBHOOK + "'\n")

    def test_creates_section_if_missing(self):
        out = setup_wizard.set_webhook("wow_dir = 'y'\n", "kill", WEBHOOK)
        self.assertIn("[webhooks]\npvp_kills = '" + WEBHOOK + "'", out)

    def test_upgrades_an_old_config_to_the_new_names(self):
        old = ("# Copy this file to config.toml.\n\n"
               "# REQUIRED: Discord webhook.\n# Keep it private.\nwebhook_url = 'https://discord.com/api/webhooks/1/d'\n\n"
               "wow_dir = 'C:\\WoW'\n\n"
               "[notify]\ndeath = true\nflag = false      # only sent if enabled in game\n\n"
               "[mentions]\npvp = \"<@42>\"\n\n"
               "[webhooks]\n# Optional per-event webhooks.\nkill = 'https://discord.com/api/webhooks/2/k'\n"
               "flag = 'https://discord.com/api/webhooks/3/p'\npvp = 'https://discord.com/api/webhooks/3/p'\n")
        new = setup_wizard.upgrade_names(old)
        self.assertNotIn("webhook_url", new)
        self.assertNotIn("REQUIRED: Discord webhook", new)
        for line in ("deaths = true", "pvp_flag = false      # only sent", 'pvp_alerts = "<@42>"',
                     "default = 'https://discord.com/api/webhooks/1/d'", "pvp_kills = 'https://discord.com/api/webhooks/2/k'",
                     "pvp_flag = 'https://discord.com/api/webhooks/3/p'", "pvp_alerts = 'https://discord.com/api/webhooks/3/p'"):
            self.assertIn("\n" + line, new)
        path = Path(tempfile.mkdtemp()) / "config.toml"
        for text in (old, new):
            path.write_text(text, encoding="utf-8")
            cfg = config.load(path)
            self.assertEqual((cfg.webhook_for("death"), cfg.webhook_for("kill"), cfg.webhook_for("flag")),
                             ("https://discord.com/api/webhooks/1/d", "https://discord.com/api/webhooks/2/k",
                              "https://discord.com/api/webhooks/3/p"))
            self.assertFalse(cfg.enabled("flag"))
            self.assertEqual(cfg.pvp_mention, "<@42>")
        self.assertEqual(setup_wizard.upgrade_names(new), new, "already upgraded: unchanged")

    def test_command_saves_and_posts_sample_to_that_channel(self):
        path = self.write_config()
        with mock.patch.object(cli.discord, "post") as post, redirect_stdout(io.StringIO()):
            code = cli.set_webhook(path, "pvp", None, ask=lambda _: WEBHOOK + "/pvp")
        self.assertEqual(code, 0)
        cfg = config.load(path)
        self.assertEqual(cfg.webhook_for("pvp"), WEBHOOK + "/pvp")
        self.assertEqual(cfg.webhook_for("flag"), WEBHOOK + "/pvp")  # flag alerts follow the PvP channel
        self.assertEqual(cfg.webhook_for("death"), WEBHOOK)
        url, body = post.call_args.args
        self.assertEqual(url, WEBHOOK + "/pvp")
        self.assertIn("under attack", body["embeds"][0]["title"])

    def test_command_rejects_bad_url_without_saving(self):
        path = self.write_config()
        before = path.read_text(encoding="utf-8")
        with mock.patch.object(cli.discord, "post") as post, redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            code = cli.set_webhook(path, "kill", "https://example.com/not-a-webhook")
        self.assertEqual(code, 2)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
