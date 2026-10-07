import io
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

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
        cfg = self.run_wizard(["3", "1", "not a url", WEBHOOK, "1"], [self.wow])
        self.assertEqual(cfg.webhook_url, WEBHOOK)
        self.assertEqual(cfg.webhooks, {})
        self.assertEqual(cfg.screenshots_dir, self.wow / "Screenshots")
        self.assertEqual(cfg.wow_dir, self.wow)
        self.assertEqual(self.installed_to, [self.wow])
        self.assertTrue(cfg.notify["pvp"])

    def test_separate_channels(self):
        gold, deaths, level, pvp = (f"{WEBHOOK}/{n}" for n in ("gold", "deaths", "level", "pvp"))
        cfg = self.run_wizard(["2", deaths, level, pvp, gold, "1"], [self.wow])
        self.assertEqual(cfg.webhook_url, deaths)
        for event, url in [("death", deaths), ("level", level), ("pvp", pvp), ("flag", pvp), ("summary", gold)]:
            self.assertEqual(cfg.webhook_for(event), url, event)
        self.assertEqual(cli.channel_events(cfg), {
            deaths: ["Deaths", "Tests"], level: ["Level ups"], pvp: ["PvP alerts"],
            gold: ["Gold summary (on logout)"]})

    def test_separate_channels_enter_reuses_previous(self):
        other = WEBHOOK + "/other"
        cfg = self.run_wizard(["2", WEBHOOK, "", other, "", "1"], [self.wow])
        self.assertEqual(cfg.webhook_for("level"), WEBHOOK)
        self.assertEqual(cfg.webhook_for("summary"), other)
        self.assertEqual(cfg.webhooks, {"pvp": other, "summary": other, "flag": other})

    def test_pasted_path_with_quotes_and_apostrophe(self):
        odd = self.tmp / "Bob's Games" / "_forever_"
        odd.mkdir(parents=True)
        cfg = self.run_wizard(["1", WEBHOOK, str(self.tmp / "missing"), f'"{odd}"'], [])
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


if __name__ == "__main__":
    unittest.main()
