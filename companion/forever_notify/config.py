"""Load and validate the companion's TOML config."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import teamhooks

EVENTS = ("death", "level", "pvp", "kill", "flag", "summary", "test")
SIGNAL_EVENTS = {"DEATH": "death", "LEVEL": "level", "PVP": "pvp", "KILL": "kill", "FLAG": "flag", "TEST": "test"}


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    webhook_url: str
    screenshots_dir: Path
    saved_variables_glob: str
    delete_signal_screenshots: bool = True
    summary_grace_seconds: float = 30
    poll_seconds: float = 0.2
    notify: dict[str, bool] = field(default_factory=lambda: {e: True for e in EVENTS})
    webhooks: dict[str, str] = field(default_factory=dict)
    pvp_mention: str = ""
    wow_dir: Path | None = None
    state_file: Path | None = None  # remembers posted summaries; None = in memory only
    catch_up_seconds: float = 600  # signals saved this long before start-up are still posted

    def webhook_for(self, event: str) -> str:
        return self.webhooks.get(event) or self.webhook_url

    def enabled(self, event: str) -> bool:
        return self.notify.get(event, True)


_BUILTIN = object()  # default for load(builtin=...): use the exe's team webhooks, if any


def load(path: str | Path, builtin=_BUILTIN) -> Config:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))  # -sig: Notepad may add a BOM
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path} (copy config.example.toml to get started)")
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}")

    webhook = raw.get("webhook_url", "").strip()
    webhooks = {k: v for k, v in raw.get("webhooks", {}).items() if v}
    if not webhook:
        # No webhook of its own: use the team webhooks built into the exe; any
        # [webhooks] entries in config.toml still override them per channel.
        try:
            team = teamhooks.load_builtin() if builtin is _BUILTIN else builtin
        except teamhooks.TeamHooksError as e:
            raise ConfigError(f"Built-in team webhooks unusable ({e}); set webhook_url in {path}")
        if team:
            webhook = team[0]
            webhooks = {**team[1], **webhooks}
    if not webhook.startswith("https://"):
        raise ConfigError("webhook_url must be set to your Discord webhook URL (https://discord.com/api/webhooks/...)")

    wow_dir = raw.get("wow_dir")
    screenshots = raw.get("screenshots_dir") or (wow_dir and str(Path(wow_dir) / "Screenshots"))
    sv_glob = raw.get("saved_variables_glob") or (
        wow_dir and str(Path(wow_dir) / "WTF" / "Account" / "*" / "SavedVariables" / "ForeverNotify.lua"))
    if not screenshots or not sv_glob:
        raise ConfigError("Set wow_dir to your WoW Forever install folder (the one containing Screenshots and WTF)")

    notify = {e: True for e in EVENTS}
    notify.update({k: bool(v) for k, v in raw.get("notify", {}).items()})

    return Config(
        webhook_url=webhook,
        screenshots_dir=Path(screenshots),
        saved_variables_glob=sv_glob,
        delete_signal_screenshots=bool(raw.get("delete_signal_screenshots", True)),
        summary_grace_seconds=float(raw.get("summary_grace_seconds", 30)),
        poll_seconds=float(raw.get("poll_seconds", 0.2)),
        notify=notify,
        webhooks=webhooks,
        pvp_mention=raw.get("mentions", {}).get("pvp", ""),
        wow_dir=Path(wow_dir) if wow_dir else None,
        state_file=path.parent / "state.json",
        catch_up_seconds=float(raw.get("catch_up_minutes", 10)) * 60,
    )
