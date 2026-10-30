"""Small JSON files the companion keeps next to config.toml (posted summaries, screenshot cache, ...)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load(path: Path | None, default: Any) -> Any:
    """The file's contents, or default if there's no path, no file, or it can't be read or has the wrong shape."""
    if not path:
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def save(path: Path | None, data: Any) -> None:
    """Write via a temporary file, so a crash mid-write can't leave a half-written file. No path: do nothing."""
    if not path:
        return
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        log.warning("Could not save %s: %s", path, e)
