"""Discord webhook delivery on a background thread, with rate-limit handling."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

USER_AGENT = "ForeverNotify (https://github.com/justinmcglinn-cyber/wow-forever-discord-notifier, 0.1)"
MAX_ATTEMPTS = 5


def post(url: str, body: dict, timeout: float = 10) -> None:
    """POST a webhook body, retrying on rate limits and server errors."""
    data = json.dumps(body).encode("utf-8")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout):
                return
        except urllib.error.HTTPError as e:
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


class Sender:
    """Delivers messages in order without blocking the watcher loop."""

    def __init__(self, post_fn=post):
        self._post = post_fn
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
            url, body = self._queue.get()
            try:
                self._post(url, body)
                log.info("Sent: %s", body.get("embeds", [{}])[0].get("title", "message"))
            except Exception as e:  # keep the sender alive whatever happens
                log.error("Failed to send to Discord: %s", e)
            finally:
                self._queue.task_done()
