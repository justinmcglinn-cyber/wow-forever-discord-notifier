"""Start-up clean-up of screenshots that were already in the folder.

Signal screenshots taken while the companion wasn't running would otherwise
pile up forever. At start-up a background thread decodes every screenshot it
hasn't checked before: signals from the last few minutes are handed back to be
posted late, older signals are deleted unposted, and the player's own
screenshots are remembered in screenshot_cache.json so each one is only ever
read once (and never modified).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from . import jsonstate
from .signal_decode import decode_file

log = logging.getLogger(__name__)

PAUSE = 0.02  # seconds between files, so a big first sweep doesn't compete with the game for CPU
SAVE_EVERY = 50  # files between cache saves during a sweep


class ScreenshotCache:
    """Screenshots already checked and left in place, keyed by file name, size and modification time."""

    def __init__(self, path: Path | None):
        self._path = path
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()  # the sweep thread and the main loop both save
        self._dirty = False
        try:
            self._known = {str(k): list(v) for k, v in jsonstate.load(path, {}).get("known", {}).items()}
        except (TypeError, ValueError, AttributeError):
            self._known = {}

    @staticmethod
    def _stamp(path: Path) -> list[int] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return [st.st_size, st.st_mtime_ns]

    def is_known(self, path: Path) -> bool:
        stamp = self._stamp(path)
        with self._lock:
            return stamp is not None and self._known.get(path.name) == stamp

    def add(self, path: Path) -> None:
        stamp = self._stamp(path)
        if stamp is None:
            return
        with self._lock:
            if self._known.get(path.name) != stamp:
                self._known[path.name] = stamp
                self._dirty = True

    def forget_missing(self, present: set[str]) -> None:
        with self._lock:
            gone = [name for name in self._known if name not in present]
            for name in gone:
                del self._known[name]
            self._dirty = self._dirty or bool(gone)

    def save(self) -> None:
        if not self._path:
            return
        with self._save_lock:
            with self._lock:
                if not self._dirty:
                    return
                data = {"known": dict(self._known)}
                self._dirty = False
            jsonstate.save(self._path, data)


def _age(payload: dict[str, str], mtime: float, now: float) -> float:
    try:
        return now - int(payload["ts"])
    except (KeyError, ValueError, TypeError):
        return now - mtime


class StartupSweep:
    """Checks the screenshots present at start-up on a background thread.

    Recent signals are queued for the main loop (take them with drain());
    older ones are deleted here. Normal screenshots are added to the cache.
    """

    def __init__(self, paths: list[Path], cache: ScreenshotCache, delete: bool, recent_seconds: float,
                 now: float | None = None, pause: float = PAUSE):
        self._paths = list(paths)
        self._cache = cache
        self._delete = delete
        self._recent = recent_seconds
        self._now = time.time() if now is None else now
        self._pause = pause
        self._results: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="screenshot-sweep", daemon=True)
        self.checked = self.deleted = self.queued = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        self._thread.join(timeout)

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def drain(self) -> list[tuple[Path, dict[str, str]]]:
        items = []
        while True:
            try:
                items.append(self._results.get_nowait())
            except queue.Empty:
                return items

    def _run(self) -> None:
        try:
            self._sweep()
        except Exception:  # never take the companion down over housekeeping
            log.exception("Screenshot clean-up stopped early")
        finally:
            self._cache.save()

    def _sweep(self) -> None:
        files = []
        for path in self._paths:
            try:
                files.append((path.stat().st_mtime, path))
            except OSError:
                pass
        self._cache.forget_missing({path.name for _, path in files})
        todo = [(mtime, path) for mtime, path in files if not self._cache.is_known(path)]
        # Recent files first (oldest to newest, so late posts stay in order), then the backlog.
        cutoff = self._now - self._recent
        recent = sorted(f for f in todo if f[0] >= cutoff)
        backlog = sorted((f for f in todo if f[0] < cutoff), reverse=True)
        if len(todo) > SAVE_EVERY:
            log.info("Checking %d screenshots from before start-up for leftover notifications "
                     "(one-off; your own screenshots are only read).", len(todo))

        for mtime, path in recent + backlog:
            if self._stop.is_set():
                return
            self._check(path, mtime)
            self.checked += 1
            if self.checked % SAVE_EVERY == 0:
                self._cache.save()
            if self._pause:
                time.sleep(self._pause)

        if self.deleted or self.queued:
            log.info("Screenshot clean-up: removed %d old notification screenshot(s), %d recent one(s) to send.",
                     self.deleted, self.queued)

    def _check(self, path: Path, mtime: float) -> None:
        try:
            payload = decode_file(path)
        except (OSError, SyntaxError, ValueError):
            return  # unreadable right now; try again next start-up
        if payload is None:
            self._cache.add(path)  # one of the player's own screenshots: leave it alone
        elif _age(payload, mtime, self._now) <= self._recent:
            self._results.put((path, payload))
            self.queued += 1
        elif self._delete:
            try:
                path.unlink()
                self.deleted += 1
            except OSError as e:
                log.warning("Could not delete %s: %s", path, e)
        else:
            self._cache.add(path)  # kept by choice (delete_signal_screenshots = false)
