"""Test messages delete themselves after about a minute."""

import io
import json
import tempfile
import time
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from forever_notify import cli, config, discord, formatting
from forever_notify.app import Notifier

HOOK = "https://discord.com/api/webhooks/1/abc"


class FakeDiscord:
    """Stands in for urllib.request.urlopen and records each request."""

    def __init__(self, missing=()):
        self.requests = []
        self._missing = set(missing)
        self._next_id = 100

    def __call__(self, request, timeout=None):
        self.requests.append((request.get_method(), request.full_url,
                              json.loads(request.data) if request.data else None))
        if request.get_method() == "DELETE" and request.full_url.split("?")[0].rsplit("/", 1)[-1] in self._missing:
            raise urllib.error.HTTPError(request.full_url, 404, "Unknown Message", {}, io.BytesIO(b""))
        self._next_id += 1
        reply = json.dumps({"id": str(self._next_id)}).encode() if "wait=true" in request.full_url else b""
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = reply
        return response


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class PostAndDelete(unittest.TestCase):
    def test_normal_messages_post_without_waiting(self):
        fake = FakeDiscord()
        with mock.patch("urllib.request.urlopen", fake):
            self.assertIsNone(discord.post(HOOK, {"content": "hi"}))
        self.assertEqual(fake.requests, [("POST", HOOK, {"content": "hi"})])

    def test_expiring_messages_ask_for_the_id_and_hide_the_marker(self):
        fake = FakeDiscord()
        with mock.patch("urllib.request.urlopen", fake):
            message_id = discord.post(HOOK + "?thread_id=9", {"content": "hi", discord.DELETE_AFTER: 60})
        self.assertEqual(message_id, "101")
        method, url, body = fake.requests[0]
        self.assertEqual(url, HOOK + "?thread_id=9&wait=true")
        self.assertEqual(body, {"content": "hi"}, "the marker is never sent to Discord")

    def test_delete_targets_the_message_and_keeps_the_thread(self):
        fake = FakeDiscord()
        with mock.patch("urllib.request.urlopen", fake):
            discord.delete_message(HOOK + "?thread_id=9", "101")
        self.assertEqual(fake.requests, [("DELETE", HOOK + "/messages/101?thread_id=9", None)])

    def test_deleting_an_already_deleted_message_is_fine(self):
        with mock.patch("urllib.request.urlopen", FakeDiscord(missing={"101"})):
            discord.delete_message(HOOK, "101")  # no error


class ExpiringMessages(unittest.TestCase):
    def test_deleted_only_when_due_and_survives_restart(self):
        path = Path(tempfile.mkdtemp()) / "pending_deletes.json"
        clock, deleted = Clock(), []
        first = discord.Expiring(path, delete_fn=lambda url, mid: deleted.append(mid), clock=clock)
        first.add(HOOK, "101", 60)
        clock.now += 30
        first.run_due()
        self.assertEqual(deleted, [])

        restarted = discord.Expiring(path, delete_fn=lambda url, mid: deleted.append(mid), clock=clock)
        self.assertEqual(len(restarted), 1)
        clock.now += 31
        restarted.run_due()
        self.assertEqual(deleted, ["101"])
        self.assertEqual(len(discord.Expiring(path)), 0, "nothing left to delete after a restart")

    def test_failed_delete_is_retried_then_given_up(self):
        clock, calls = Clock(), []

        def flaky(url, mid):
            calls.append(mid)
            raise RuntimeError("offline")

        e = discord.Expiring(delete_fn=flaky, clock=clock)
        e.add(HOOK, "101", 60)
        clock.now += 61
        e.run_due()
        self.assertEqual(len(e), 1, "kept for a retry")
        clock.now += discord.Expiring.GIVE_UP_AFTER
        e.run_due()
        self.assertEqual(len(e), 0)
        self.assertEqual(len(calls), 2)

    def test_wait_and_delete_blocks_until_done(self):
        clock, deleted = Clock(), []
        e = discord.Expiring(delete_fn=lambda url, mid: deleted.append(mid), clock=clock)
        e.add(HOOK, "101", 60)
        e.add(HOOK, "102", 60)

        def sleep(seconds):
            clock.now += seconds

        e.wait_and_delete(sleep=sleep)
        self.assertEqual(deleted, ["101", "102"])
        self.assertGreaterEqual(clock.now, 1060)


class Samples(unittest.TestCase):
    def test_every_sample_is_marked_to_delete_itself(self):
        for event, body in formatting.sample_messages({"c": "Thrall", "r": "Area52"}).items():
            self.assertEqual(body[discord.DELETE_AFTER], formatting.TEST_LINGER_SECONDS, event)
            self.assertIn("deletes itself", body["embeds"][0]["description"])

    def test_real_notifications_are_not_marked(self):
        body = formatting.format_signal({"t": "DEATH", "c": "Thrall", "r": "Area52"})
        self.assertNotIn(discord.DELETE_AFTER, body)


class InGameTest(unittest.TestCase):
    def test_fnotify_test_samples_are_deleted_by_the_sender(self):
        clock, deleted, posted = Clock(), [], []
        expiring = discord.Expiring(delete_fn=lambda url, mid: deleted.append(mid), clock=clock)

        def post(url, body):
            posted.append(body)
            return str(200 + len(posted)) if body.get(discord.DELETE_AFTER) else None

        sender = discord.Sender(post_fn=post, expiring=expiring)
        cfg = config.Config(webhook_url=HOOK, screenshots_dir=Path("."), saved_variables_glob="")
        notifier = Notifier(cfg, sender.send)
        notifier.handle_signal({"t": "TEST", "c": "Thrall", "r": "Area52", "ts": str(int(time.time()))})
        notifier.handle_signal({"t": "DEATH", "c": "Thrall", "r": "Area52"})
        sender.flush()
        self.assertEqual(len(expiring), len(posted) - 1, "every sample but not the real death")

        clock.now += formatting.TEST_LINGER_SECONDS + 1
        deadline = time.time() + 5
        while len(expiring) and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(len(expiring), 0)
        self.assertEqual(len(deleted), len(posted) - 1)


class TestWebhookCommand(unittest.TestCase):
    def test_samples_are_recorded_for_deletion(self):
        cfg = config.Config(webhook_url=HOOK, screenshots_dir=Path("."), saved_variables_glob="")
        expiring = discord.Expiring()
        with mock.patch.object(cli.discord, "post", side_effect=lambda url, body: "7"), \
                redirect_stdout(io.StringIO()):
            self.assertTrue(cli.send_tests(cfg, expiring))
        self.assertEqual(len(expiring), len(formatting.sample_messages({})))


if __name__ == "__main__":
    unittest.main()
