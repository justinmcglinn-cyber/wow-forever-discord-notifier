import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forever_notify import config, setup_wizard, teamhooks

URL = "https://discord.com/api/webhooks/123456789/secret-token"


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


class CommittedTeamData(unittest.TestCase):
    def test_team_data_decrypts_and_hides_urls(self):
        path = Path(teamhooks.__file__).with_name("team_data.py")
        if not path.exists():
            self.skipTest("no team webhooks generated")
        self.assertNotIn("discord", path.read_text(encoding="utf-8").lower())
        main, hooks = teamhooks.load_builtin()
        for url in [main, *hooks.values()]:
            self.assertTrue(url.startswith(setup_wizard.WEBHOOK_PREFIXES))


class TeamSetup(unittest.TestCase):
    def test_setup_only_asks_for_wow_folder_and_writes_no_urls(self):
        tmp = Path(tempfile.mkdtemp())
        wow = tmp / "World of Warcraft" / "_forever_"
        (wow / "WTF").mkdir(parents=True)
        path = tmp / "config.toml"
        answers = iter(["1"])  # only the folder question
        with redirect_stdout(io.StringIO()):
            setup_wizard.run(path, ask=lambda _: next(answers), candidates=[wow],
                             install_addon=lambda _: True, team_webhooks=True)
        text = path.read_text(encoding="utf-8")
        self.assertIn("webhook_url = ''", text)
        self.assertNotIn("webhooks/1", text)  # no real webhook written (only the template's placeholders)
        cfg = config.load(path, builtin=(URL, {"kill": URL + "/kills"}))
        self.assertEqual(cfg.webhook_for("kill"), URL + "/kills")
        self.assertEqual(cfg.screenshots_dir, wow / "Screenshots")


if __name__ == "__main__":
    unittest.main()
