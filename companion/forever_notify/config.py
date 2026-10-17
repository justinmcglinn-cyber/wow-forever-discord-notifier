"""Load and validate the companion's TOML config."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

EVENTS = ("death", "level", "pvp", "kill", "flag", "summary", "test")
SIGNAL_EVENTS = {"DEATH": "death", "LEVEL": "level", "PVP": "pvp", "KILL": "kill", "BATTLE": "kill", "FLAG": "flag", "TEST": "test"}
# Each channel needs a webhook (directly or through default); PvP flag notices fall back to PvP alerts.
CHANNEL_EVENTS = ("death", "level", "pvp", "kill", "summary")

# The name each event has in config.toml ([webhooks] and [notify]). The short
# event names are what older configs used; they still work.
NAMES = {"death": "deaths", "level": "level_ups", "pvp": "pvp_alerts", "flag": "pvp_flag", "kill": "pvp_kills",
         "summary": "gold_summary", "test": "test_messages"}
ALIASES = {**{event: event for event in EVENTS}, **{name: event for event, name in NAMES.items()}}


class ConfigError(ValueError):
    pass


class NoWebhookError(ConfigError):
    """config.toml has no webhooks (e.g. from a version with the team's webhooks built in)."""


@dataclass
class Config:
    webhook_url: str  # default: used by any event without its own webhook
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
        return self.webhooks.get(event) or (event == "flag" and self.webhooks.get("pvp")) or self.webhook_url

    def enabled(self, event: str) -> bool:
        return self.notify.get(event, True)


def by_event(table: dict) -> dict:
    """A config.toml section keyed by event; the new name wins if both are present."""
    old = {k: v for k, v in table.items() if k in EVENTS}
    new = {ALIASES[k]: v for k, v in table.items() if k in ALIASES and k not in EVENTS}
    return {**old, **new}


def parse_webhooks(raw: dict) -> tuple[str, dict[str, str]]:
    """The default webhook and the per-event ones from parsed config.toml."""
    section = raw.get("webhooks", {})
    default = str(section.get("default") or raw.get("webhook_url") or "").strip()
    return default, {event: str(url).strip() for event, url in by_event(section).items() if str(url).strip()}


def load(path: str | Path) -> Config:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))  # -sig: Notepad may add a BOM
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path} (copy config.example.toml to get started)")
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}")

    webhook, webhooks = parse_webhooks(raw)
    if not webhook and not webhooks:
        raise NoWebhookError("No Discord webhooks set. Run 'ForeverNotify.exe setup' and paste your team code "
                             "or webhook URL.")
    for event in CHANNEL_EVENTS:
        url = webhooks.get(event) or webhook
        if not url.startswith("https://"):
            raise ConfigError(f"[webhooks] {NAMES[event]} must be a Discord webhook URL "
                              "(https://discord.com/api/webhooks/...), or set default for every channel")

    wow_dir = raw.get("wow_dir")
    screenshots = raw.get("screenshots_dir") or (wow_dir and str(Path(wow_dir) / "Screenshots"))
    sv_glob = raw.get("saved_variables_glob") or (
        wow_dir and str(Path(wow_dir) / "WTF" / "Account" / "*" / "SavedVariables" / "ForeverNotify.lua"))
    if not screenshots or not sv_glob:
        raise ConfigError("Set wow_dir to your WoW Forever install folder (the one containing Screenshots and WTF)")

    notify = {e: True for e in EVENTS}
    notify.update({k: bool(v) for k, v in by_event(raw.get("notify", {})).items()})
    mentions = raw.get("mentions", {})

    return Config(
        webhook_url=webhook,
        screenshots_dir=Path(screenshots),
        saved_variables_glob=sv_glob,
        delete_signal_screenshots=bool(raw.get("delete_signal_screenshots", True)),
        summary_grace_seconds=float(raw.get("summary_grace_seconds", 30)),
        poll_seconds=float(raw.get("poll_seconds", 0.2)),
        notify=notify,
        webhooks=webhooks,
        pvp_mention=mentions.get("pvp_alerts", mentions.get("pvp", "")),
        wow_dir=Path(wow_dir) if wow_dir else None,
        state_file=path.parent / "state.json",
        catch_up_seconds=float(raw.get("catch_up_minutes", 10)) * 60,
    )
