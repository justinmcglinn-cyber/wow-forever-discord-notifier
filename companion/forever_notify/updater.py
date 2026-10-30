"""Check GitHub for a newer release and, if the player agrees, update the exe in place.

At start-up the exe asks GitHub for the latest release. If it's newer than the
add-on version bundled in this exe (release tags and add-on versions always
match), the player is asked whether to update. On yes, the new exe is
downloaded, checked against the SHA-256 GitHub publishes for it, swapped in
(Windows lets a running exe be renamed, not overwritten) and started; the old
copy is deleted on the next start. Nothing is ever installed without asking,
and any failure leaves the current version running.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import addon_install
from .discord import USER_AGENT

log = logging.getLogger(__name__)

REPO = "justinmcglinn-cyber/wow-forever-discord-notifier"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
EXE_NAME = "ForeverNotify.exe"
OLD_EXE = "ForeverNotify.old.exe"
NEW_EXE = "ForeverNotify.new.exe"
DOWNLOAD = "ForeverNotify.download"
PROMPT_SECONDS = 30
CHECK_TIMEOUT = 5


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    tag: str
    version: tuple[int, ...]
    url: str  # file to download (the exe, or the release zip that contains it)
    sha256: str  # expected SHA-256 of that file, lower-case hex; "" if GitHub gave none
    is_zip: bool
    page: str


def parse_version(text: str | None) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def version_text(version: tuple[int, ...] | None) -> str:
    return ".".join(map(str, version)) if version else "unknown"


def current_version() -> tuple[int, ...] | None:
    """This exe's version: the bundled add-on's, which always matches the release tag."""
    return addon_install.toc_version(addon_install.bundled_addon())


def _get_json(url: str, timeout: float = CHECK_TIMEOUT) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _asset_digest(asset: dict) -> str:
    digest = str(asset.get("digest") or "")
    return digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else ""


def _notes_hash(notes: str, filename: str) -> str:
    """The SHA-256 the release workflow writes into the notes, e.g. 'SHA-256 of `ForeverNotify.exe` …: `ABC…`'."""
    match = re.search(r"SHA-256 of `" + re.escape(filename) + r"`[^`\n]*?:\s*`([0-9A-Fa-f]{64})`", notes)
    return match.group(1).lower() if match else ""


def latest_release(fetch: Callable[[str], dict] = _get_json) -> Release | None:
    """The latest published release, or None if there isn't a usable one."""
    data = fetch(API_LATEST)
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    version = parse_version(tag)
    if version is None:
        return None
    notes = str(data.get("body") or "")
    assets = {str(a.get("name")): a for a in data.get("assets") or [] if isinstance(a, dict)}
    asset, is_zip = assets.get(EXE_NAME), False
    if asset is None:
        asset = next((a for name, a in assets.items() if name.lower().endswith(".zip")), None)
        is_zip = True
    if asset is None:
        return None
    url = str(asset.get("browser_download_url") or "")
    if not url.startswith(DOWNLOAD_PREFIX):
        return None  # only ever download from this repo's releases
    sha256 = _asset_digest(asset) or _notes_hash(notes, str(asset.get("name")))
    return Release(tag=tag, version=version, url=url, sha256=sha256, is_zip=is_zip,
                   page=str(data.get("html_url") or RELEASES_PAGE))


def download(url: str, dest: Path, sha256: str, opener=urllib.request.urlopen, report=print) -> Path:
    """Download to dest, checking the SHA-256 as it arrives. A mismatch deletes the file."""
    if not sha256:
        raise UpdateError("GitHub didn't publish a checksum for this download, so it can't be verified")
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=60) as response, open(dest, "wb") as out:
            headers = getattr(response, "headers", None)
            total = int(headers.get("Content-Length") or 0) if headers is not None else 0
            done, last_quarter = 0, 0
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                quarter = done * 4 // total if total else 0
                if quarter > last_quarter:  # progress at 25/50/75/100%
                    last_quarter = quarter
                    report(f"  {min(100, quarter * 25)}% of {total / 1_048_576:.0f} MB")
    except OSError as e:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"download failed: {e}") from e
    if digest.hexdigest() != sha256.lower():
        dest.unlink(missing_ok=True)
        raise UpdateError("the download doesn't match the checksum GitHub published; nothing was changed")
    return dest


def extract_exe(zip_path: Path, dest: Path) -> Path:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            name = next((n for n in archive.namelist() if n.replace("\\", "/").rsplit("/", 1)[-1] == EXE_NAME), None)
            if name is None:
                raise UpdateError(f"the release zip has no {EXE_NAME}")
            with archive.open(name) as src, open(dest, "wb") as out:
                while chunk := src.read(256 * 1024):
                    out.write(chunk)
    except zipfile.BadZipFile as e:
        raise UpdateError(f"the release zip is damaged: {e}") from e
    return dest


def _retry(action: Callable[[], None], attempts: int = 5, delay: float = 0.5) -> None:
    """Antivirus can hold a new exe open for a moment after it's written."""
    for attempt in range(attempts):
        try:
            action()
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def replace_exe(new_exe: Path, exe: Path) -> Path:
    """Swap new_exe in for exe (which may be running). Returns where the old copy went."""
    old = exe.with_name(OLD_EXE)
    if old.exists():
        _retry(old.unlink)
    _retry(lambda: exe.replace(old))  # a running exe can be renamed, just not overwritten
    try:
        _retry(lambda: new_exe.replace(exe))
    except OSError:
        old.replace(exe)  # put the working copy back
        raise
    return old


def relaunch(exe: Path, argv: list[str], popen=subprocess.Popen) -> None:
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # start fresh, don't reuse this process's unpacked files
    env.pop("_MEIPASS2", None)
    popen([str(exe), *argv], env=env)


def exit_now() -> None:
    """End this (old) copy at once after a swap. PyInstaller reads not-yet-loaded code from the exe file on
    demand, and that file is now the new version, so nothing more may run here, not even normal shutdown."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
    os._exit(0)


def cleanup_leftovers(exe: Path) -> None:
    """Remove the previous exe and any half-finished download from an earlier update."""
    for name in (OLD_EXE, NEW_EXE, DOWNLOAD):
        try:
            exe.with_name(name).unlink(missing_ok=True)
        except OSError:
            pass  # still in use; next start


def ask_with_timeout(prompt: str, seconds: float | None) -> str | None:
    """Read a line from the console, or None if nothing is typed in time (seconds=None waits as long as it takes)."""
    if seconds is None:
        try:
            return input(prompt)
        except EOFError:
            return None
    print(prompt, end="", flush=True)
    if sys.platform == "win32":
        import msvcrt
        deadline, chars = time.monotonic() + seconds, []
        while time.monotonic() < deadline:
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # arrow/function key: ignore it and its second code
                    msvcrt.getwch()
                elif ch in ("\r", "\n"):
                    print()
                    return "".join(chars)
                elif ch == "\x03":
                    raise KeyboardInterrupt
                elif ch == "\b":
                    if chars:
                        chars.pop()
                        print("\b \b", end="", flush=True)
                else:
                    chars.append(ch)
                    print(ch, end="", flush=True)
            time.sleep(0.05)
        print()
        return None
    import select
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if not ready:
        print()
        return None
    return sys.stdin.readline().strip()


class UpdateState:
    """update.json next to config.toml: the release the player skipped ("skip") and the last one installed
    ("installed"), so a release whose exe carries an older version number isn't installed over and over."""

    def __init__(self, path: Path | None):
        self._path = path

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8")) if self._path else {}
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str) -> str:
        return str(self._load().get(key, ""))

    def set(self, **values: str) -> None:
        if not self._path:
            return
        try:
            self._path.write_text(json.dumps({**self._load(), **values}), encoding="utf-8")
        except OSError as e:
            log.warning("Could not save %s: %s", self._path, e)


def install(release: Release, exe: Path, report=print, opener=urllib.request.urlopen) -> None:
    """Download, verify and swap in the release's exe. Raises UpdateError, leaving the current exe in place."""
    downloaded = exe.with_name(DOWNLOAD)
    new_exe = exe.with_name(NEW_EXE)
    try:
        report(f"Downloading {release.tag}…")
        download(release.url, downloaded, release.sha256, opener=opener, report=report)
        if release.is_zip:
            extract_exe(downloaded, new_exe)
            downloaded.unlink(missing_ok=True)
        else:
            downloaded.replace(new_exe)
        replace_exe(new_exe, exe)
    except OSError as e:
        raise UpdateError(f"couldn't replace {exe.name}: {e}") from e
    finally:
        downloaded.unlink(missing_ok=True)
        new_exe.unlink(missing_ok=True)


def offer_update(state_dir: Path | None, frozen: bool, exe: Path | None = None, argv: list[str] | None = None,
                 interactive: bool = True, force: bool = False, ask=ask_with_timeout,
                 fetch: Callable[[str], dict] = _get_json, opener=urllib.request.urlopen,
                 restart=relaunch, report=print) -> bool:
    """Check for a newer release and offer to install it. Returns True if a restart was started (caller exits).

    force: asked for with the `update` command, so a skipped version is offered again and there's no time limit.
    """
    exe = exe or Path(sys.executable)
    if frozen:
        cleanup_leftovers(exe)
    current = current_version()
    if current is None:
        return False
    try:
        release = latest_release(fetch)
    except Exception as e:  # offline, GitHub down, rate-limited: try again next start
        log.debug("Update check failed: %s", e)
        if force:
            report(f"Couldn't check for updates: {e}")
        return False
    if release is None or release.version <= current:
        if force:
            report(f"ForeverNotify v{version_text(current)} is the latest version.")
        return False
    state = UpdateState(state_dir / "update.json" if state_dir else None)
    if not force and state.get("skip") == release.tag:
        log.info("ForeverNotify %s is available (skipped). Run 'ForeverNotify.exe update' to install it.", release.tag)
        return False
    if not force and state.get("installed") == release.tag:
        # Installed before, yet this exe still reports an older version: the release's exe is mislabelled.
        # Offering it again would loop forever.
        log.warning("Release %s was installed but reports v%s; not offering it again. Download it yourself from %s",
                    release.tag, version_text(current), release.page)
        return False

    header = f"ForeverNotify {release.tag} is available (you have v{version_text(current)})."
    if not frozen:
        report(f"{header} You're running from source: update with 'git pull'. {release.page}")
        return False
    if not interactive:
        log.warning("%s Download it from %s", header, release.page)
        return False
    if not release.sha256:
        report(f"{header} It can't be verified automatically, so download it yourself from {release.page}")
        return False

    if force:
        answer = ask(f"{header} Update now? [Y/n]: ", None)
    else:
        answer = ask(f"{header}\nUpdate now? [Y]es / [n]o / [s]kip this version "
                     f"(carrying on without updating in {PROMPT_SECONDS}s): ", PROMPT_SECONDS)
    if answer is None:
        report("Carrying on without updating; I'll ask again next time.")
        return False
    answer = answer.strip().lower()
    if answer in ("s", "skip"):
        state.set(skip=release.tag)
        report(f"Skipping {release.tag}. Run 'ForeverNotify.exe update' if you change your mind.")
        return False
    if answer not in ("", "y", "yes"):
        return False

    try:
        install(release, exe, report=report, opener=opener)
    except UpdateError as e:
        report(f"Update failed: {e}. Carrying on with v{version_text(current)}.")
        return False
    state.set(installed=release.tag)
    report(f"Updated to {release.tag}. Restarting…")
    restart(exe, list(argv or []))
    return True
