"""Copy the bundled ForeverNotify add-on into the game's Interface\\AddOns folder."""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ADDON_NAME = "ForeverNotify"


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
