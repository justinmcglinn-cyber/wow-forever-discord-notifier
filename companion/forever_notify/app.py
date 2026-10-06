"""Watch the Screenshots folder and SavedVariables, and forward events to Discord."""

from __future__ import annotations

import glob
import logging
import time
from pathlib import Path
from typing import Callable

from . import formatting
from .config import SIGNAL_EVENTS, Config
from .luasv import LuaParseError, parse_saved_variables
from .signal_decode import decode_file

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".tga", ".jpg", ".jpeg"}
GIVE_UP_AFTER = 10  # seconds to keep retrying a file that won't open


class FolderWatcher:
    """Reports files that appear after start-up once their size stops changing."""

    def __init__(self, list_files: Callable[[], list[Path]]):
        self._list = list_files
        self._seen = set(self._safe_list())
        self._pending: dict[Path, tuple[int, float]] = {}

    def _safe_list(self) -> list[Path]:
        try:
            return self._list()
        except OSError:
            return []

    def poll(self, now: float) -> list[Path]:
        ready = []
        for path in self._safe_list():
            if path in self._seen:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            previous = self._pending.get(path)
            if previous and previous[0] == size and size > 0:
                ready.append(path)
            elif not previous or previous[0] != size:
                self._pending[path] = (size, previous[1] if previous else now)
        return ready

    def done(self, path: Path) -> None:
        self._seen.add(path)
        self._pending.pop(path, None)

    def retry_or_drop(self, path: Path, now: float) -> None:
        size, first = self._pending.get(path, (0, now))
        if now - first > GIVE_UP_AFTER:
            self.done(path)
        else:
            self._pending[path] = (-1, first)  # force a fresh size check next poll


class ChangeWatcher:
    """Reports files matching a glob whose modification time changed since start-up."""

    def __init__(self, pattern: str):
        self._pattern = pattern
        self._mtimes = {p: self._mtime(p) for p in self._paths()}

    def _paths(self) -> list[str]:
        return glob.glob(self._pattern)

    @staticmethod
    def _mtime(path: str) -> float | None:
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None

    def poll(self) -> list[str]:
        changed = []
        for path in self._paths():
            mtime = self._mtime(path)
            if mtime is not None and mtime != self._mtimes.get(path):
                self._mtimes[path] = mtime
                changed.append(path)
        return changed


class Notifier:
    """Turns decoded signals and logout summaries into Discord messages."""

    def __init__(self, config: Config, send: Callable[[str, dict], None]):
        self.config = config
        self.send = send
        self._pending_summaries: dict[str, tuple[float, dict]] = {}
        self._last_signal_ts: dict[str, int] = {}
        self._posted_summaries: set[tuple] = set()

    @staticmethod
    def _char_key(name, realm) -> str:
        return f"{name}-{realm}"

    def handle_signal(self, payload: dict[str, str]) -> None:
        kind = payload.get("t", "")
        key = self._char_key(payload.get("c"), payload.get("r"))
        try:
            ts = int(payload.get("ts") or 0)
        except ValueError:
            ts = 0
        self._last_signal_ts[key] = max(ts, self._last_signal_ts.get(key, 0))
        self._cancel_summary_if_still_playing(key)

        event = SIGNAL_EVENTS.get(kind)
        if event is None:
            log.info("Signal %s from %s", kind or "?", key)
            return
        if not self.config.enabled(event):
            log.info("Skipping %s (disabled in config)", kind)
            return
        body = formatting.format_signal(payload, self.config.pvp_mention)
        if body:
            self.send(self.config.webhook_for(event), body)

    def handle_saved_variables(self, text: str, now: float) -> None:
        try:
            data = parse_saved_variables(text)
        except (LuaParseError, IndexError) as e:
            log.warning("Could not parse SavedVariables: %s", e)
            return
        summary = (data.get("ForeverNotifyDB") or {}).get("lastSummary")
        if not isinstance(summary, dict) or not summary.get("id"):
            return
        ident = (summary.get("id"), summary.get("stop"))
        if ident in self._posted_summaries:
            return
        if summary.get("enabled") is False or not self.config.enabled("summary"):
            self._posted_summaries.add(ident)
            return
        key = self._char_key(summary.get("char"), summary.get("realm"))
        self._pending_summaries[key] = (now + self.config.summary_grace_seconds, summary)
        log.info("Logout detected for %s; waiting %.0fs in case it was a /reload",
                 key, self.config.summary_grace_seconds)
        self._cancel_summary_if_still_playing(key)

    def _cancel_summary_if_still_playing(self, key: str) -> None:
        pending = self._pending_summaries.get(key)
        if pending and self._last_signal_ts.get(key, 0) >= int(pending[1].get("stop", 0)):
            log.info("%s is still in game (UI reload); summary discarded", key)
            self._posted_summaries.add((pending[1].get("id"), pending[1].get("stop")))
            del self._pending_summaries[key]

    def tick(self, now: float) -> None:
        for key, (deadline, summary) in list(self._pending_summaries.items()):
            if now >= deadline:
                del self._pending_summaries[key]
                self._posted_summaries.add((summary.get("id"), summary.get("stop")))
                self.send(self.config.webhook_for("summary"), formatting.format_summary(summary))


def _list_images(folder: Path) -> Callable[[], list[Path]]:
    def list_files() -> list[Path]:
        return [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    return list_files


def process_screenshot(path: Path, notifier: Notifier, delete: bool) -> bool:
    """Decode one screenshot. Returns False if it couldn't be read yet."""
    try:
        payload = decode_file(path)
    except OSError:
        return False
    if payload is None:
        log.debug("%s is a normal screenshot", path.name)
        return True
    log.info("Signal %s from %s", payload.get("t"), path.name)
    notifier.handle_signal(payload)
    if delete:
        try:
            path.unlink()
        except OSError as e:
            log.warning("Could not delete %s: %s", path, e)
    return True


def run(config: Config, send: Callable[[str, dict], None], stop: Callable[[], bool] = lambda: False) -> None:
    if not config.screenshots_dir.is_dir():
        log.warning("Screenshots folder %s doesn't exist yet; it will be watched once created",
                    config.screenshots_dir)
    screenshots = FolderWatcher(_list_images(config.screenshots_dir))
    saved_vars = ChangeWatcher(config.saved_variables_glob)
    notifier = Notifier(config, send)
    log.info("Watching %s", config.screenshots_dir)
    log.info("Watching %s", config.saved_variables_glob)

    while not stop():
        now = time.time()
        for path in screenshots.poll(now):
            if process_screenshot(path, notifier, config.delete_signal_screenshots):
                screenshots.done(path)
            else:
                screenshots.retry_or_drop(path, now)
        for path in saved_vars.poll():
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning("Could not read %s: %s", path, e)
                continue
            notifier.handle_saved_variables(text, now)
        notifier.tick(now)
        time.sleep(config.poll_seconds)
