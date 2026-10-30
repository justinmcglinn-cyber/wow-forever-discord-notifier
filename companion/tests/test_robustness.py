"""One bad notification or summary must never stop the companion."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from forever_notify import app, config, formatting, updater

from .test_companion import encode_image
from .test_updater import api_reply


def cfg(**kwargs):
    return config.Config(webhook_url="https://x", screenshots_dir=Path("."), saved_variables_glob="", **kwargs)


class OddValues(unittest.TestCase):
    def test_signals_with_odd_numbers_still_format(self):
        for payload in ({"t": "LEVEL", "c": "A", "new": "25", "prev": "?", "sess": "1e400"},
                        {"t": "KILL", "c": "A", "multi": "two", "streak": ""},
                        {"t": "BATTLE", "c": "A", "k": "x", "mine": None, "dur": "nan"}):
            body = formatting.format_signal(payload)
            self.assertIn("embeds", body, payload["t"])
        level = formatting.format_signal({"t": "LEVEL", "c": "A", "new": "25", "prev": "?"})
        self.assertNotIn("Played", str(level), "an unreadable time is left out, not shown as 0s")

    def test_summary_with_odd_numbers_still_formats(self):
        body = formatting.format_summary({"startMoney": "12.5g", "endMoney": None, "stop": "x", "accountMoney": "?"})
        self.assertIn("gold summary", body["embeds"][0]["title"])

    def test_to_int(self):
        self.assertEqual(formatting.to_int("42"), 42)
        self.assertEqual(formatting.to_int(7.9), 7)
        self.assertEqual(formatting.to_int("inf", -1), -1)
        self.assertIsNone(formatting.to_int("?", None))


class KeepsRunning(unittest.TestCase):
    def test_a_failing_signal_is_logged_skipped_and_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            signal = Path(d) / "WoWScrnShot_1.png"
            encode_image(b"t=DEATH\nc=Thrall\nr=Area52").save(signal)
            notifier = app.Notifier(cfg(), lambda url, body: None)
            with mock.patch.object(notifier, "handle_signal", side_effect=RuntimeError("boom")), \
                    self.assertLogs(app.log, "ERROR"):
                self.assertTrue(app.process_screenshot(signal, notifier, delete=True))
            self.assertFalse(signal.exists())

    def test_a_summary_that_cant_be_formatted_is_skipped_once(self):
        sent = []
        notifier = app.Notifier(cfg(summary_grace_seconds=0), lambda url, body: sent.append(body))
        notifier.handle_saved_variables('ForeverNotifyDB = { ["lastSummary"] = { ["id"] = "A-B:1", '
                                        '["char"] = "A", ["realm"] = "B", ["stop"] = 100 } }', 0)
        with mock.patch.object(app.formatting, "format_summary", side_effect=KeyError("x")), \
                self.assertLogs(app.log, "ERROR"):
            notifier.tick(1)
        notifier.tick(2)
        self.assertEqual(sent, [])

    def test_watch_loop_survives_an_unexpected_error(self):
        with tempfile.TemporaryDirectory() as d:
            shots = Path(d) / "Screenshots"
            shots.mkdir()
            config_ = cfg(poll_seconds=0.05)
            config_.screenshots_dir = shots
            config_.saved_variables_glob = str(Path(d) / "none" / "*.lua")
            calls = []

            def explode(path, *args):
                calls.append(path)
                raise MemoryError("decoder blew up")

            deadline = time.time() + 3
            started = []

            def stop():
                if not started:
                    started.append(1)
                    encode_image(b"t=DEATH\nc=A\nr=B").save(shots / "WoWScrnShot_2.png")
                return len(calls) > 0 and time.time() > deadline - 2.5 or time.time() > deadline

            with mock.patch.object(app, "process_screenshot", explode), self.assertLogs(app.log, "ERROR"):
                app.run(config_, lambda url, body: None, stop=stop, is_game_running=lambda: False)
            self.assertEqual(len(calls), 1, "the broken file is skipped, not retried every poll")


class NoUpdateLoop(unittest.TestCase):
    def test_a_mislabelled_release_is_installed_once_not_forever(self):
        d = Path(tempfile.mkdtemp())
        exe = d / "ForeverNotify.exe"
        exe.write_bytes(b"MZ old")
        new_bytes = b"MZ new ForeverNotify build"  # matches the checksum in api_reply()
        opener = lambda request, timeout=None: _Response(new_bytes)
        with mock.patch.object(updater, "current_version", return_value=(0, 1, 13)):
            first = updater.offer_update(d, True, exe=exe, ask=lambda p, s: "y", fetch=lambda url: api_reply(tag="v0.1.14"),
                                         opener=opener, restart=mock.Mock(), report=lambda *_: None)
            asked = []
            # The "new" exe still says 0.1.13: don't offer v0.1.14 again at start-up.
            second = updater.offer_update(d, True, exe=exe, ask=lambda p, s: asked.append(p),
                                          fetch=lambda url: api_reply(tag="v0.1.14"), report=lambda *_: None)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(asked, [])


class _Response:
    def __init__(self, data):
        self._data, self.headers = [data, b""], {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._data.pop(0) if self._data else b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    unittest.main()
