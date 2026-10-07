"""Copy the bundled ForeverNotify add-on into the game's Interface\\AddOns folder."""

from __future__ import annotations

import filecmp
import logging
import re
import shutil
import sys
from pathlib import Path

ADDON_NAME = "ForeverNotify"

log = logging.getLogger(__name__)


def bundled_addon() -> Path:
    """The add-on shipped inside the exe, or the repo's addon folder when run from source."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "addon" / ADDON_NAME
    return Path(__file__).resolve().parents[2] / "addon" / ADDON_NAME


def installed_addon(wow_dir: Path) -> Path:
    return Path(wow_dir) / "Interface" / "AddOns" / ADDON_NAME


def status(wow_dir: Path, source: Path | None = None) -> str:
    """'missing', 'outdated', 'current', or 'unknown' if there's no bundled copy to compare with."""
    source = source or bundled_addon()
    if not source.is_dir():
        return "unknown"
    target = installed_addon(wow_dir)
    if not target.is_dir():
        return "missing"
    names = sorted(p.name for p in source.iterdir() if p.is_file())
    match, mismatch, errors = filecmp.cmpfiles(source, target, names, shallow=False)
    return "current" if not mismatch and not errors else "outdated"


def install(wow_dir: Path, source: Path | None = None) -> Path:
    """Replace the installed add-on with the bundled one. Settings live in WTF, so they're kept."""
    source = source or bundled_addon()
    if not source.is_dir():
        raise FileNotFoundError(f"Bundled add-on not found at {source}")
    target = installed_addon(wow_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def toc_version(addon_dir: Path) -> tuple[int, ...] | None:
    """The '## Version:' from the add-on's .toc, e.g. (0, 1, 0)."""
    try:
        text = (addon_dir / f"{ADDON_NAME}.toc").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    match = re.search(r"(?m)^##\s*Version:\s*([\d.]+)", text)
    return tuple(int(n) for n in match.group(1).strip(".").split(".")) if match else None


def sync(wow_dir: Path, source: Path | None = None) -> str:
    """Install or update the add-on unless it's already current or newer than the bundled copy.

    Returns 'installed', 'updated', 'current', 'kept-newer' or 'unknown'. Raises OSError if copying fails.
    """
    source = source or bundled_addon()
    state = status(wow_dir, source)
    if state in ("current", "unknown"):
        return state
    if state == "outdated":
        installed, bundled = toc_version(installed_addon(wow_dir)), toc_version(source)
        if installed and bundled and installed > bundled:
            return "kept-newer"
    install(wow_dir, source)
    return "installed" if state == "missing" else "updated"


def _version_text(path: Path) -> str:
    version = toc_version(path)
    return ".".join(map(str, version)) if version else "unknown version"


def sync_and_report(wow_dir: Path) -> None:
    """Start-up check: keep the game's add-on in step with this companion, logging what happened."""
    target = installed_addon(wow_dir)
    try:
        result = sync(wow_dir)
    except OSError as e:
        log.warning("Could not install/update the add-on in %s: %s. Copy it there yourself, "
                    "or run ForeverNotify.exe as administrator once.", target.parent, e)
        return
    if result in ("installed", "updated"):
        log.info("%s the add-on (v%s) in %s. If WoW is running, type /reload in game.",
                 result.capitalize(), _version_text(target), target)
    elif result == "kept-newer":
        log.warning("The installed add-on (v%s) is newer than this companion's (v%s); left it alone. "
                    "Consider updating ForeverNotify.exe.", _version_text(target), _version_text(bundled_addon()))
    elif result == "current":
        log.info("Add-on v%s is up to date.", _version_text(target))


def install_and_report(wow_dir: Path) -> bool:
    """Install with friendly console output. Returns True on success."""
    try:
        target = install(wow_dir)
    except OSError as e:
        print(f"Could not install the add-on: {e}")
        print(f"Copy the ForeverNotify folder into {installed_addon(wow_dir).parent} yourself,"
              " or run ForeverNotify.exe as administrator once.")
        return False
    print(f"Installed the add-on to {target}")
    print("If WoW is already running, type /reload in game to load it.")
    return True
