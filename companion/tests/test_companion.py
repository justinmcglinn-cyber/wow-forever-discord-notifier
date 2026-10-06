import os
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from forever_notify import config, formatting
from forever_notify.app import FolderWatcher, Notifier, process_screenshot
from forever_notify.luasv import parse_saved_variables
from forever_notify.signal_decode import COLUMNS, decode_bytes, fletcher16


def encode_image(payload: bytes, block=6, size=(800, 300)) -> Image.Image:
    """Python twin of Signal.Encode + Draw, for decoder unit tests."""
    data = bytes([1, len(payload) >> 8, len(payload) & 0xFF]) + payload
    hi, lo = fletcher16(data)
    raw = b"FN" + data + bytes([hi, lo])
    bits = [(byte >> s) & 1 for byte in raw for s in range(7, -1, -1)]
    bits += [0] * (-len(bits) % 3)
    colours = [bits[i] * 4 + bits[i + 1] * 2 + bits[i + 2] for i in range(0, len(bits), 3)]
    image = Image.new("RGB", size, (40, 90, 60))
    cells = [7 if c % 2 == 0 else 0 for c in range(COLUMNS)] + colours
    for i, c in enumerate(cells):
        x, y = (i % COLUMNS) * block, (i // COLUMNS) * block
        rgb = ((c >> 2 & 1) * 255, (c >> 1 & 1) * 255, (c & 1) * 255)
        image.paste(rgb, (x, y, x + block, y + block))
    return image


class Decoder(unittest.TestCase):
    def test_round_trip(self):
        payload = "t=TEST\nc=Thrall\nzone=Orgrimmar › Valley of Strength".encode()
        self.assertEqual(decode_bytes(encode_image(payload)), payload)

    def test_plain_screenshot_is_ignored(self):
        self.assertIsNone(decode_bytes(Image.new("RGB", (800, 600), (255, 255, 255))))
        self.assertIsNone(decode_bytes(Image.new("RGB", (800, 600), (0, 0, 0))))

    def test_corrupted_block_fails_checksum(self):
        image = encode_image(b"t=TEST\nc=Thrall")
        image.paste((255, 255, 255), (6 * 20, 6, 6 * 21, 12))  # flip a data block
        image.paste((0, 0, 0), (6 * 21, 6, 6 * 22, 12))
        self.assertIsNone(decode_bytes(image))


class SavedVariables(unittest.TestCase):
    def test_parses_wow_format(self):
        text = '''
ForeverNotifyDB = {
\t["settings"] = {
\t\t["death"] = true,
\t\t["pvpCooldown"] = 10,
\t},
\t["name"] = "Line\\nTwo \\"quoted\\" \\195\\169",
\t["list"] = {
\t\t"a", -- [1]
\t\t"b", -- [2]
\t},
\t["neg"] = -1.5,
\t["none"] = nil,
}
OtherDB = false
'''
        data = parse_saved_variables(text)
        db = data["ForeverNotifyDB"]
        self.assertEqual(db["settings"], {"death": True, "pvpCooldown": 10})
        self.assertEqual(db["name"], 'Line\nTwo "quoted" é')
        self.assertEqual(db["list"], {1: "a", 2: "b"})
        self.assertEqual(db["neg"], -1.5)
        self.assertIs(data["OtherDB"], False)


class Formatting(unittest.TestCase):
    def test_money(self):
        self.assertEqual(formatting.money(0), "0c")
        self.assertEqual(formatting.money(5), "5c")
        self.assertEqual(formatting.money(12345), "1g 23s 45c")
        self.assertEqual(formatting.money(123456789), "12,345g 67s 89c")
        self.assertEqual(formatting.money(-250, signed=True), "-2s 50c")
        self.assertEqual(formatting.money(250, signed=True), "+2s 50c")

    def test_duration(self):
        self.assertEqual(formatting.duration(42), "42s")
        self.assertEqual(formatting.duration(125), "2m 5s")
        self.assertEqual(formatting.duration(4320), "1h 12m")

    def test_pvp_message(self):
        body = formatting.format_signal({
            "t": "PVP", "c": "Thrall", "r": "Area52", "lv": "23", "ts": "1790000000",
            "zone": "Hillsbrad Foothills", "sz": "Southshore", "x": "52.4", "y": "49.1", "pvp": "contested",
            "hp": "64", "near": "2", "a1": "Gankster|Stormrage|60|Rogue|Undead|Shadow Council",
        }, pvp_mention="<@42>")
        self.assertEqual(body["content"], "<@42>")
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "⚔️ Thrall is under attack!")
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertEqual(fields["Attackers"], "**Gankster**-Stormrage (Lv 60 Undead Rogue) <Shadow Council>")
        self.assertEqual(fields["Location"], "Hillsbrad Foothills › Southshore (52.4, 49.1) · Contested")
        self.assertEqual(fields["Your health"], "64%")

    def test_death_messages(self):
        pvp = formatting.format_signal({"t": "DEATH", "c": "Thrall", "k": "Gankster|||Rogue|Undead|", "kpvp": "1"})
        self.assertIn("Killed by **Gankster** (Undead Rogue) — **PvP**", pvp["embeds"][0]["description"])
        npc = formatting.format_signal({"t": "DEATH", "c": "Thrall", "k": "Hillsbrad Farmer", "kpvp": "0"})
        self.assertEqual(npc["embeds"][0]["description"], "Killed by **Hillsbrad Farmer**")

    def test_internal_signals_not_posted(self):
        self.assertIsNone(formatting.format_signal({"t": "RELOAD"}))


class ConfigLoading(unittest.TestCase):
    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8")
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_derives_paths_and_overrides(self):
        cfg = config.load(self.write(
            "webhook_url = 'https://discord.com/api/webhooks/1/x'\n"
            "wow_dir = '/games/wow/_forever_'\n"
            "[notify]\nflag = false\n"
            "[webhooks]\npvp = 'https://discord.com/api/webhooks/2/y'\n"
        ))
        self.assertEqual(cfg.screenshots_dir, Path("/games/wow/_forever_/Screenshots"))
        self.assertTrue(cfg.saved_variables_glob.endswith("ForeverNotify.lua"))
        self.assertFalse(cfg.enabled("flag"))
        self.assertTrue(cfg.enabled("pvp"))
        self.assertEqual(cfg.webhook_for("pvp"), "https://discord.com/api/webhooks/2/y")
        self.assertEqual(cfg.webhook_for("death"), "https://discord.com/api/webhooks/1/x")

    def test_missing_webhook_is_an_error(self):
        with self.assertRaises(config.ConfigError):
            config.load(self.write("wow_dir = '/x'\n"))

    def test_example_config_parses(self):
        example = Path(__file__).resolve().parents[1] / "config.example.toml"
        text = example.read_text(encoding="utf-8").replace('webhook_url = ""', "webhook_url = 'https://x'")
        cfg = config.load(self.write(text))
        self.assertTrue(cfg.enabled("pvp"))


class Watching(unittest.TestCase):
    def test_folder_watcher_waits_for_stable_new_files(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "old.png").write_bytes(b"x")
            watcher = FolderWatcher(lambda: list(folder.iterdir()))
            new = folder / "new.png"
            new.write_bytes(b"abc")
            self.assertEqual(watcher.poll(0), [])      # first sighting
            self.assertEqual(watcher.poll(0.5), [new])  # size stable
            watcher.done(new)
            self.assertEqual(watcher.poll(1), [])

    def test_signal_screenshot_is_posted_and_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            cfg = config.Config(webhook_url="https://x", screenshots_dir=Path(d), saved_variables_glob="")
            notifier = Notifier(cfg, lambda url, body: sent.append((url, body)))
            signal = Path(d) / "WoWScrnShot_100626_101500.png"
            encode_image(b"t=LEVEL\nc=Thrall\nr=Area52\nnew=24").save(signal)
            mine = Path(d) / "WoWScrnShot_100626_101600.png"
            Image.new("RGB", (800, 600), (10, 120, 200)).save(mine)

            self.assertTrue(process_screenshot(signal, notifier, delete=True))
            self.assertTrue(process_screenshot(mine, notifier, delete=True))
            self.assertFalse(signal.exists())
            self.assertTrue(mine.exists(), "user screenshots are never deleted")
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1]["embeds"][0]["title"], "⬆️ Thrall reached level 24")

    def test_disabled_event_not_sent(self):
        sent = []
        cfg = config.Config(webhook_url="https://x", screenshots_dir=Path("."), saved_variables_glob="",
                            notify={"death": False})
        Notifier(cfg, lambda url, body: sent.append(body)).handle_signal({"t": "DEATH", "c": "A", "r": "B"})
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
