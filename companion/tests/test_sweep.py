import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from forever_notify import config
from forever_notify.app import Notifier, process_screenshot, run
from forever_notify.signal_decode import decode_file
from forever_notify.sweep import ScreenshotCache, StartupSweep

from .test_companion import encode_image

NOW = 1_790_000_000


def write_signal(folder: Path, name: str, payload: str, age: float, now: float = NOW) -> Path:
    path = folder / name
    encode_image(payload.encode()).save(path)
    os.utime(path, (now - age, now - age))
    return path


def write_photo(folder: Path, name: str, age: float, now: float = NOW) -> Path:
    path = folder / name
    Image.new("RGB", (800, 600), (30, 90, 160)).save(path)
    os.utime(path, (now - age, now - age))
    return path


class Sweep(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.shots = self.dir / "Screenshots"
        self.shots.mkdir()
        self.cache_file = self.dir / "screenshot_cache.json"

    def sweep(self, delete=True):
        s = StartupSweep(sorted(self.shots.iterdir()), ScreenshotCache(self.cache_file), delete, 600, now=NOW, pause=0)
        s.start()
        s.join(10)
        return s

    def test_old_signals_deleted_recent_queued_photos_untouched(self):
        old = write_signal(self.shots, "WoWScrnShot_old.png", f"t=DEATH\nc=Thrall\nr=Area52\nts={NOW - 7200}", 7200)
        death = write_signal(self.shots, "WoWScrnShot_death.png", f"t=DEATH\nc=Thrall\nr=Area52\nts={NOW - 120}", 120)
        pvp = write_signal(self.shots, "WoWScrnShot_pvp.png", f"t=PVP\nc=Thrall\nr=Area52\nts={NOW - 30}", 30)
        photo = write_photo(self.shots, "WoWScrnShot_sunset.png", 7200)
        photo_bytes = photo.read_bytes()

        s = self.sweep()
        self.assertFalse(old.exists(), "old signal removed")
        self.assertTrue(photo.exists())
        self.assertEqual(photo.read_bytes(), photo_bytes, "player's screenshot never modified")
        queued = s.drain()
        self.assertEqual([p for p, _ in queued], [death, pvp], "recent signals queued oldest first")
        self.assertEqual((s.checked, s.deleted, s.queued), (4, 1, 2))
        self.assertTrue(death.exists(), "recent signals are left for the main loop to post and delete")

    def test_photos_are_only_read_once(self):
        photo = write_photo(self.shots, "WoWScrnShot_sunset.png", 7200)
        self.sweep()
        with mock.patch("forever_notify.sweep.decode_file", wraps=decode_file) as decode:
            self.sweep()
        decode.assert_not_called()
        self.assertTrue(photo.exists())

        os.utime(photo, (NOW, NOW))  # edited since: checked again
        with mock.patch("forever_notify.sweep.decode_file", wraps=decode_file) as decode:
            self.sweep()
        decode.assert_called_once()

    def test_cache_forgets_deleted_files(self):
        photo = write_photo(self.shots, "WoWScrnShot_sunset.png", 7200)
        self.sweep()
        photo.unlink()
        self.sweep()
        self.assertNotIn("WoWScrnShot_sunset.png", self.cache_file.read_text())

    def test_nothing_deleted_when_deletion_is_off(self):
        old = write_signal(self.shots, "WoWScrnShot_old.png", f"t=DEATH\nc=Thrall\nr=Area52\nts={NOW - 7200}", 7200)
        s = self.sweep(delete=False)
        self.assertTrue(old.exists())
        self.assertEqual(s.deleted, 0)
        with mock.patch("forever_notify.sweep.decode_file", wraps=decode_file) as decode:
            self.sweep(delete=False)
        decode.assert_not_called()

    def test_unreadable_file_is_retried_next_time(self):
        broken = self.shots / "WoWScrnShot_broken.png"
        broken.write_bytes(b"\x89PNG\r\n\x1a\n not really")
        self.sweep()
        self.assertTrue(broken.exists())
        self.assertNotIn("broken", self.cache_file.read_text() if self.cache_file.exists() else "")

    def test_live_photos_are_cached_for_next_start_up(self):
        cfg = config.Config(webhook_url="https://x", screenshots_dir=self.shots, saved_variables_glob="")
        cache = ScreenshotCache(self.cache_file)
        photo = write_photo(self.shots, "WoWScrnShot_live.png", 0)
        self.assertTrue(process_screenshot(photo, Notifier(cfg, lambda *a: None), True, cache))
        self.assertTrue(cache.is_known(photo))


class LateSignals(unittest.TestCase):
    def notifier(self, sent):
        cfg = config.Config(webhook_url="https://x", screenshots_dir=Path("."), saved_variables_glob="",
                            summary_grace_seconds=30)
        return Notifier(cfg, lambda url, body: sent.append(body))

    def test_late_death_is_posted_and_marked(self):
        sent = []
        self.notifier(sent).handle_late_signal({"t": "DEATH", "c": "Thrall", "r": "Area52", "ts": str(NOW - 60)})
        self.assertEqual(len(sent), 1)
        self.assertIn("sent late", sent[0]["embeds"][0]["footer"]["text"])

    def test_late_pvp_and_test_signals_are_not_posted(self):
        sent = []
        n = self.notifier(sent)
        n.handle_late_signal({"t": "PVP", "c": "Thrall", "r": "Area52", "ts": str(NOW - 60), "a1": "Gankster"})
        n.handle_late_signal({"t": "TEST", "c": "Thrall", "r": "Area52", "ts": str(NOW - 60)})
        self.assertEqual(sent, [])

    def test_late_reload_signal_still_cancels_the_summary(self):
        sent = []
        n = self.notifier(sent)
        sv = ('ForeverNotifyDB = { ["lastSummary"] = { ["id"] = "Thrall-Area52:1", ["char"] = "Thrall", '
              f'["realm"] = "Area52", ["start"] = {NOW - 3600}, ["stop"] = {NOW - 40}, '
              '["startMoney"] = 0, ["endMoney"] = 500 } }')
        n.handle_saved_variables(sv, NOW)
        n.handle_late_signal({"t": "RELOAD", "c": "Thrall", "r": "Area52", "ts": str(NOW - 37)})
        n.tick(NOW + 60)
        self.assertEqual(sent, [])


class RunCleansUp(unittest.TestCase):
    def test_run_posts_recent_death_and_clears_leftovers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shots = root / "Screenshots"
            shots.mkdir()
            now = time.time()
            old = write_signal(shots, "WoWScrnShot_old.png", f"t=LEVEL\nc=Thrall\nr=Area52\nnew=20\nts={int(now) - 7200}",
                               7200, now)
            recent = write_signal(shots, "WoWScrnShot_new.png", f"t=DEATH\nc=Thrall\nr=Area52\nts={int(now) - 90}",
                                  90, now)
            photo = write_photo(shots, "WoWScrnShot_sunset.png", 7200, now)
            cfg = config.Config(webhook_url="https://x", screenshots_dir=shots,
                                saved_variables_glob=str(root / "none" / "*.lua"), poll_seconds=0.05,
                                state_file=root / "state.json")
            sent = []
            deadline = time.time() + 3
            run(cfg, lambda url, body: sent.append(body),
                stop=lambda: (sent and not old.exists() and not recent.exists()) or time.time() > deadline,
                is_game_running=lambda: False)

            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["embeds"][0]["title"], "💀 Thrall died")
            self.assertFalse(old.exists())
            self.assertFalse(recent.exists())
            self.assertTrue(photo.exists())
            self.assertTrue((root / "screenshot_cache.json").exists())


if __name__ == "__main__":
    unittest.main()
