import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forever_notify import config, setup_wizard

WEBHOOK = "https://discord.com/api/webhooks/123/abc"


class SetupWizard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.wow = self.tmp / "World of Warcraft" / "_forever_"
        (self.wow / "WTF").mkdir(parents=True)

    def run_wizard(self, answers, candidates):
        answers = iter(answers)
        path = self.tmp / "config.toml"
        with redirect_stdout(io.StringIO()):
            setup_wizard.run(path, ask=lambda _: next(answers), candidates=candidates)
        return config.load(path)

    def test_picks_detected_folder_and_rejects_bad_webhook(self):
        cfg = self.run_wizard(["not a url", WEBHOOK, "1"], [self.wow])
        self.assertEqual(cfg.webhook_url, WEBHOOK)
        self.assertEqual(cfg.screenshots_dir, self.wow / "Screenshots")
        self.assertTrue(cfg.notify["pvp"])

    def test_pasted_path_with_quotes_and_apostrophe(self):
        odd = self.tmp / "Bob's Games" / "_forever_"
        odd.mkdir(parents=True)
        cfg = self.run_wizard([WEBHOOK, str(self.tmp / "missing"), f'"{odd}"'], [])
        self.assertEqual(cfg.screenshots_dir, odd / "Screenshots")

    def test_find_wow_dirs(self):
        (self.tmp / "World of Warcraft" / "_retail_").mkdir()
        self.assertEqual(setup_wizard.find_wow_dirs([str(self.tmp)]), [self.wow])


if __name__ == "__main__":
    unittest.main()
