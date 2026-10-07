import io
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
    def test_folder_watcher_offers_new_files_at_once_and_retries(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "old.png").write_bytes(b"x")
            watcher = FolderWatcher(lambda: list(folder.iterdir()))
            new = folder / "new.png"
            new.write_bytes(b"")
            self.assertEqual(watcher.poll(0), [])       # nothing written yet
            new.write_bytes(b"abc")
            self.assertEqual(watcher.poll(0.2), [new])  # offered as soon as it has content
            watcher.retry_or_drop(new, 0.2)             # couldn't decode yet (still being written)
            self.assertEqual(watcher.poll(0.4), [new])  # offered again
            watcher.done(new)
            self.assertEqual(watcher.poll(0.6), [])
            stuck = folder / "stuck.png"
            stuck.write_bytes(b"abc")
            watcher.poll(1)
            watcher.retry_or_drop(stuck, 12)            # gives up after GIVE_UP_AFTER seconds
            self.assertEqual(watcher.poll(12.2), [])

    def test_half_written_signal_is_retried_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            cfg = config.Config(webhook_url="https://x", screenshots_dir=Path(d), saved_variables_glob="")
            notifier = Notifier(cfg, lambda url, body: sent.append(body))
            buf = io.BytesIO()
            encode_image(b"t=PVP\nc=Thrall\nr=Area52\na1=Gankster").save(buf, "PNG")
            signal = Path(d) / "WoWScrnShot_100626_101500.png"
            signal.write_bytes(buf.getvalue()[: len(buf.getvalue()) // 2])
            self.assertFalse(process_screenshot(signal, notifier, delete=True))  # retry later
            signal.write_bytes(buf.getvalue())
            self.assertTrue(process_screenshot(signal, notifier, delete=True))
            self.assertEqual(len(sent), 1)

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


WEBHOOKS = {"level": "https://hook/level", "pvp": "https://hook/pvp", "flag": "https://hook/pvp",
            "summary": "https://hook/gold"}


def multi_channel_config(**kwargs):
    return config.Config(webhook_url="https://hook/deaths", screenshots_dir=Path("."), saved_variables_glob="",
                         webhooks=dict(WEBHOOKS), **kwargs)


class TestMessages(unittest.TestCase):
    def test_samples_cover_every_channel_and_are_marked(self):
        samples = formatting.sample_messages({"c": "Frostbolt", "r": "Realm", "lv": "24", "zone": "Wetlands"},
                                             pvp_mention="<@1>")
        self.assertEqual(set(samples), {"death", "level", "pvp", "summary"})
        for body in samples.values():
            self.assertTrue(body["embeds"][0]["title"].startswith("🧪 TEST · "))
            self.assertIn("Test message", body["embeds"][0]["description"])
        self.assertIn("Frostbolt reached level 25", samples["level"]["embeds"][0]["title"])
        self.assertEqual(samples["pvp"]["content"], "<@1>")

    def test_in_game_test_posts_a_sample_to_each_channel(self):
        sent = []
        Notifier(multi_channel_config(), lambda url, body: sent.append((url, body["embeds"][0]["title"]))) \
            .handle_signal({"t": "TEST", "c": "Frostbolt", "r": "Realm", "ts": "1791373687"})
        urls = [url for url, _ in sent]
        self.assertEqual(urls, ["https://hook/deaths", "https://hook/level", "https://hook/pvp", "https://hook/gold"])
        self.assertIn("died", sent[0][1])
        self.assertIn("gold summary", sent[3][1])


def saved_vars(stop, summary_id="Frostbolt-Realm:1000"):
    return ('ForeverNotifyDB = {["lastSummary"] = {["id"] = "%s", ["char"] = "Frostbolt", ["realm"] = "Realm", '
            '["start"] = 1000, ["stop"] = %d, ["startMoney"] = 100, ["endMoney"] = 250, ["enabled"] = true}}'
            % (summary_id, stop))


class SummaryCatchUp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sent = []

    def notifier(self):
        cfg = multi_channel_config(state_file=self.tmp / "state.json", summary_grace_seconds=30)
        return Notifier(cfg, lambda url, body: self.sent.append(url))

    def test_missed_logout_posted_once_when_game_closed(self):
        now = 1_800_000_000
        n = self.notifier()
        n.catch_up(saved_vars(now - 600), now, game_running=False)
        n.tick(now)
        self.assertEqual(self.sent, ["https://hook/gold"])
        # Restarting the companion doesn't post it again.
        n = self.notifier()
        n.catch_up(saved_vars(now - 600), now + 60, game_running=False)
        n.tick(now + 60)
        self.assertEqual(self.sent, ["https://hook/gold"])

    def test_old_summary_not_posted_while_game_running(self):
        now = 1_800_000_000
        n = self.notifier()
        n.catch_up(saved_vars(now - 600), now, game_running=True)  # maybe a /reload
        n.tick(now + 100)
        self.assertEqual(self.sent, [])

    def test_logout_just_before_start_up_gets_normal_grace(self):
        now = 1_800_000_000
        n = self.notifier()
        n.catch_up(saved_vars(now - 4), now, game_running=True)
        n.tick(now + 10)
        self.assertEqual(self.sent, [])  # still within the /reload grace period
        n.tick(now + 31)
        self.assertEqual(self.sent, ["https://hook/gold"])

    def test_live_logout_then_unchanged_save_posts_once(self):
        now = 1_800_000_000
        n = self.notifier()
        n.handle_saved_variables(saved_vars(now), now)
        n.tick(now + 31)
        n.handle_saved_variables(saved_vars(now), now + 200)  # game exits from character select
        n.tick(now + 300)
        self.assertEqual(self.sent, ["https://hook/gold"])


if __name__ == "__main__":
    unittest.main()
