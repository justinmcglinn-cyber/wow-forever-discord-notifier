"""Watch the Screenshots folder and SavedVariables, and forward events to Discord."""

from __future__ import annotations

import glob
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from . import formatting
from .config import SIGNAL_EVENTS, Config
from .luasv import LuaParseError, parse_saved_variables
from .signal_decode import decode_file
from .sweep import ScreenshotCache, StartupSweep

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".tga", ".jpg", ".jpeg"}
GIVE_UP_AFTER = 10  # seconds to keep retrying a file that won't open
RECENT_LOGOUT = 90  # a summary saved this many seconds before start-up is handled as if seen live
CATCH_UP_MAX = 24 * 3600  # older unposted summaries are posted at start-up only if WoW isn't running
LATE_KINDS = {"DEATH", "LEVEL"}  # still worth posting late; PvP alerts and tests are stale within minutes
CACHE_SAVE_INTERVAL = 60  # seconds between saves of the screenshot cache while running


class FolderWatcher:
    """Reports files that appear after start-up, as soon as they have any content.

    A file the game is still writing simply fails to decode; the caller then
    calls retry_or_drop and it's offered again on the next poll. This is faster
    than waiting for the size to settle, which matters for PvP alerts.
    """

    def __init__(self, list_files: Callable[[], list[Path]]):
        self._list = list_files
        self.initial = self._safe_list()  # already there at start-up: left to the start-up sweep
        self._seen = set(self.initial)
        self._first_seen: dict[Path, float] = {}

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
            self._first_seen.setdefault(path, now)
            if size > 0:
                ready.append(path)
        return ready

    def done(self, path: Path) -> None:
        self._seen.add(path)
        self._first_seen.pop(path, None)

    def retry_or_drop(self, path: Path, now: float) -> None:
        if now - self._first_seen.get(path, now) > GIVE_UP_AFTER:
            self.done(path)


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


class PostedSummaries:
    """Logout summaries already posted (or deliberately skipped), kept across restarts in state.json."""

    KEEP = 50

    def __init__(self, path: Path | None = None):
        self._path = path
        self._items: list[tuple[str, int]] = []
        if path:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._items = [self._key(i) for i in data.get("posted_summaries", [])]
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    @staticmethod
    def _key(ident) -> tuple[str, int]:
        summary_id, stop = ident
        try:
            stop = int(stop)
        except (TypeError, ValueError):
            stop = 0
        return str(summary_id), stop

    def __contains__(self, ident) -> bool:
        return self._key(ident) in self._items

    def add(self, ident) -> None:
        key = self._key(ident)
        if key in self._items:
            return
        self._items = (self._items + [key])[-self.KEEP:]
        if self._path:
            try:
                self._path.write_text(json.dumps({"posted_summaries": self._items}), encoding="utf-8")
            except OSError as e:
                log.warning("Could not save %s: %s", self._path, e)


class Notifier:
    """Turns decoded signals and logout summaries into Discord messages."""

    def __init__(self, config: Config, send: Callable[[str, dict], None]):
        self.config = config
        self.send = send
        self._pending_summaries: dict[str, tuple[float, dict]] = {}
        self._last_signal_ts: dict[str, int] = {}
        self._posted_summaries = PostedSummaries(config.state_file)

    @staticmethod
    def _char_key(name, realm) -> str:
        return f"{name}-{realm}"

    def _note_activity(self, payload: dict[str, str]) -> str:
        """Any signal shows the character was in game at its timestamp (e.g. a /reload, not a logout)."""
        key = self._char_key(payload.get("c"), payload.get("r"))
        try:
            ts = int(payload.get("ts") or 0)
        except ValueError:
            ts = 0
        self._last_signal_ts[key] = max(ts, self._last_signal_ts.get(key, 0))
        self._cancel_summary_if_still_playing(key)
        return key

    def handle_late_signal(self, payload: dict[str, str]) -> None:
        """A signal saved shortly before start-up: deaths and level-ups are posted, marked as late."""
        if payload.get("t") in LATE_KINDS:
            self.handle_signal({**payload, "late": "1"})
        else:
            self._note_activity(payload)
            log.info("Not posting %s from before start-up (only useful live).", payload.get("t") or "?")

    def handle_signal(self, payload: dict[str, str]) -> None:
        kind = payload.get("t", "")
        key = self._note_activity(payload)

        event = SIGNAL_EVENTS.get(kind)
        if event is None:
            log.info("Signal %s from %s", kind or "?", key)
            return
        if not self.config.enabled(event):
            log.info("Skipping %s (disabled in config)", kind)
            return
        if kind == "TEST":  # a sample of every notification, each to its own channel
            for sample_event, body in formatting.sample_messages(payload, self.config.pvp_mention).items():
                if self.config.enabled(sample_event):
                    self.send(self.config.webhook_for(sample_event), body)
            return
        body = formatting.format_signal(payload, self.config.pvp_mention)
        if body:
            self.send(self.config.webhook_for(event), body)

    @staticmethod
    def _summary(text: str) -> dict | None:
        try:
            data = parse_saved_variables(text)
        except (LuaParseError, IndexError) as e:
            log.warning("Could not parse SavedVariables: %s", e)
            return None
        summary = (data.get("ForeverNotifyDB") or {}).get("lastSummary")
        return summary if isinstance(summary, dict) and summary.get("id") else None

    def catch_up(self, text: str, now: float, game_running: bool) -> None:
        """At start-up, deal with a logout summary saved while the companion wasn't watching."""
        summary = self._summary(text)
        if summary is None:
            return
        ident = (summary.get("id"), summary.get("stop"))
        if ident in self._posted_summaries:
            log.info("Last logout summary was already posted.")
            return
        try:
            age = now - int(summary.get("stop", 0))
        except (TypeError, ValueError):
            return
        when = time.strftime("%H:%M", time.localtime(now - age))
        if age <= RECENT_LOGOUT:
            # Saved moments before start-up: treat it like a logout seen live.
            self.handle_saved_variables(text, now)
        elif not game_running and age <= CATCH_UP_MAX:
            log.info("Posting the summary from your logout at %s (saved while the companion wasn't running).", when)
            key = self._char_key(summary.get("char"), summary.get("realm"))
            self._pending_summaries[key] = (now, summary)
        else:
            reason = "WoW is running, so it may have been a /reload" if game_running else "it's too old"
            log.info("Not posting the last summary (from %s): %s.", when, reason)

    def handle_saved_variables(self, text: str, now: float) -> None:
        summary = self._summary(text)
        if summary is None:
            log.info("Game saved the add-on's data (no logout summary in it).")
            return
        ident = (summary.get("id"), summary.get("stop"))
        if ident in self._posted_summaries:
            log.info("Game saved the add-on's data (no new logout summary).")
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


def _timing(path: Path) -> str:
    """How long the game took to save the screenshot and how soon we read it (Windows creation time)."""
    if sys.platform != "win32":
        return ""
    try:
        st = path.stat()
    except OSError:
        return ""
    return f" (game saved it in {max(0.0, st.st_mtime - st.st_ctime):.2f}s, read {max(0.0, time.time() - st.st_mtime):.2f}s later)"


def process_screenshot(path: Path, notifier: Notifier, delete: bool, cache: ScreenshotCache | None = None) -> bool:
    """Decode one screenshot. Returns False if it couldn't be read yet."""
    try:
        payload = decode_file(path)
    except (OSError, SyntaxError, ValueError):  # usually still being written: retry next poll
        return False
    if payload is None:
        log.debug("%s is a normal screenshot", path.name)
        if cache:
            cache.add(path)  # so the next start-up sweep doesn't read it again
        return True
    log.info("Signal %s from %s%s", payload.get("t"), path.name, _timing(path))
    notifier.handle_signal(payload)
    if delete:
        try:
            path.unlink()
        except OSError as e:
            log.warning("Could not delete %s: %s", path, e)
    return True


def game_running(config: Config) -> bool:
    """True if a WoW executable from the configured install is running (or we can't tell)."""
    wow_dir = config.wow_dir or config.screenshots_dir.parent
    names = {p.name.lower() for p in Path(wow_dir).glob("Wow*.exe")}
    if not names or sys.platform != "win32":
        return True
    try:
        result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return True
    running = {line.split('","')[0].strip('"').lower() for line in result.stdout.splitlines() if line}
    return bool(names & running)


def run(config: Config, send: Callable[[str, dict], None], stop: Callable[[], bool] = lambda: False,
        is_game_running: Callable[[], bool] | None = None) -> None:
    if not config.screenshots_dir.is_dir():
        log.warning("Screenshots folder %s doesn't exist yet; it will be watched once created",
                    config.screenshots_dir)
    screenshots = FolderWatcher(_list_images(config.screenshots_dir))
    saved_vars = ChangeWatcher(config.saved_variables_glob)
    notifier = Notifier(config, send)
    log.info("Watching %s", config.screenshots_dir)
    log.info("Watching %s", config.saved_variables_glob)

    running = (is_game_running or (lambda: game_running(config)))()
    for path in glob.glob(config.saved_variables_glob):
        try:
            notifier.catch_up(Path(path).read_text(encoding="utf-8", errors="replace"), time.time(), running)
        except OSError as e:
            log.warning("Could not read %s: %s", path, e)

    cache = ScreenshotCache(config.state_file.with_name("screenshot_cache.json") if config.state_file else None)
    sweep = StartupSweep(screenshots.initial, cache, config.delete_signal_screenshots, config.catch_up_seconds)
    sweep.start()
    last_cache_save = time.time()

    try:
        while not stop():
            now = time.time()
            for path, payload in sweep.drain():
                log.info("Signal %s from %s (saved before start-up)", payload.get("t"), path.name)
                notifier.handle_late_signal(payload)
                if config.delete_signal_screenshots:
                    try:
                        path.unlink()
                    except OSError as e:
                        log.warning("Could not delete %s: %s", path, e)
            for path in screenshots.poll(now):
                if process_screenshot(path, notifier, config.delete_signal_screenshots, cache):
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
            if now - last_cache_save >= CACHE_SAVE_INTERVAL:
                cache.save()
                last_cache_save = now
            time.sleep(config.poll_seconds)
    finally:
        sweep.stop()
        cache.save()
