"""Discord webhook delivery on a background thread, with rate-limit handling."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

USER_AGENT = "ForeverNotify (https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier, 0.1)"
MAX_ATTEMPTS = 5

# Body key (never sent to Discord): seconds after which the posted message deletes itself.
DELETE_AFTER = "_delete_after"


def _with_query(url: str, **params: str) -> str:
    """Add query parameters, keeping any already in the webhook URL (e.g. thread_id)."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query) + list(params.items())
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _message_url(url: str, message_id: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(path=parts.path.rstrip("/") + f"/messages/{message_id}"))


def _request(url: str, method: str, data: bytes | None = None, timeout: float = 10, ok_codes=()) -> bytes:
    """Send a request, retrying on rate limits, server errors and network failures."""
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code in ok_codes:
                return b""
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read() or b"{}").get("retry_after", 1))
                except ValueError:
                    wait = 1.0
                log.warning("Discord rate limit, retrying in %.1fs", wait)
                time.sleep(wait)
                continue
            if 500 <= e.code < 600 and attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)
                continue
            detail = e.read()[:300].decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord returned HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"Could not reach Discord: {e}") from e
            time.sleep(2 ** attempt)
    raise RuntimeError("Discord delivery failed after retries")


def post(url: str, body: dict, timeout: float = 10) -> str | None:
    """POST a webhook body. Returns the message id if the body asks to be deleted later."""
    linger = body.get(DELETE_AFTER)
    payload = {k: v for k, v in body.items() if not k.startswith("_")}
    data = json.dumps(payload).encode("utf-8")
    if not linger:
        _request(url, "POST", data, timeout)
        return None
    reply = _request(_with_query(url, wait="true"), "POST", data, timeout)  # wait=true returns the message
    try:
        return str(json.loads(reply)["id"])
    except (ValueError, KeyError, TypeError):
        log.warning("Discord didn't say which message was posted; this test message won't delete itself.")
        return None


def delete_message(url: str, message_id: str, timeout: float = 10) -> None:
    """Delete a message this webhook posted. Already gone (404) counts as done."""
    _request(_message_url(url, message_id), "DELETE", timeout=timeout, ok_codes=(404,))


class Expiring:
    """Messages to delete later. Kept in a JSON file (if given) so a restart still deletes them."""

    GIVE_UP_AFTER = 24 * 3600  # stop retrying a delete this long after it was due

    def __init__(self, path: Path | None = None, delete_fn=delete_message, clock=time.time):
        self._path = path
        self._delete = delete_fn
        self._clock = clock
        self._lock = threading.Lock()
        self._items: list[dict] = []
        if path:
            try:
                self._items = [i for i in json.loads(path.read_text(encoding="utf-8")).get("pending", [])
                               if isinstance(i, dict) and {"url", "id", "due"} <= i.keys()]
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def add(self, url: str, message_id: str, after: float) -> None:
        with self._lock:
            self._items.append({"url": url, "id": str(message_id), "due": self._clock() + float(after)})
            self._save()

    def next_due(self) -> float | None:
        with self._lock:
            return min((i["due"] for i in self._items), default=None)

    def run_due(self) -> None:
        """Delete every message whose time is up; failures are retried on a later call."""
        now = self._clock()
        with self._lock:
            due = [i for i in self._items if i["due"] <= now]
        for item in due:
            try:
                self._delete(item["url"], item["id"])
                log.info("Removed a test message.")
            except Exception as e:
                if now - item["due"] < self.GIVE_UP_AFTER:
                    log.warning("Couldn't remove a test message yet (%s); will retry.", e)
                    continue
                log.warning("Giving up removing a test message: %s", e)
            with self._lock:
                if item in self._items:
                    self._items.remove(item)
                    self._save()

    def wait_and_delete(self, poll: float = 1.0, sleep=time.sleep) -> None:
        """Block until every pending message is deleted (for one-off commands)."""
        while True:
            next_due = self.next_due()
            if next_due is None:
                return
            remaining = next_due - self._clock()
            if remaining > 0:
                sleep(min(poll, remaining))
            self.run_due()

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps({"pending": self._items}), encoding="utf-8")
            tmp.replace(self._path)
        except OSError as e:
            log.warning("Could not save %s: %s", self._path, e)


class Sender:
    """Delivers messages in order without blocking the watcher loop, and deletes expiring ones when due."""

    def __init__(self, post_fn=post, expiring: Expiring | None = None):
        self._post = post_fn
        self._expiring = expiring if expiring is not None else Expiring()  # an empty one is falsy
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="discord-sender", daemon=True)
        self._thread.start()

    def send(self, url: str, body: dict) -> None:
        self._queue.put((url, body))

    def flush(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)

    def _run(self) -> None:
        while True:
            try:
                url, body = self._queue.get(timeout=1)
            except queue.Empty:
                self._run_due()
                continue
            try:
                message_id = self._post(url, body)
                if message_id and body.get(DELETE_AFTER):
                    self._expiring.add(url, message_id, body[DELETE_AFTER])
                log.info("Sent: %s", body.get("embeds", [{}])[0].get("title", "message"))
            except Exception as e:  # keep the sender alive whatever happens
                log.error("Failed to send to Discord: %s", e)
            finally:
                self._queue.task_done()
            self._run_due()

    def _run_due(self) -> None:
        try:
            self._expiring.run_due()
        except Exception as e:
            log.error("Failed to remove expired messages: %s", e)
