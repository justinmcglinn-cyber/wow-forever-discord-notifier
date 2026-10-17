"""First-run setup: ask for the team code or webhooks and the WoW folder, then write config.toml."""

from __future__ import annotations

import re
import string
import sys
import tomllib
from pathlib import Path
from typing import Callable

from . import addon_install, config, teamhooks

WEBHOOK_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                    "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")
# (event, label) for each channel the wizard asks about (config.NAMES has their config.toml names);
# PvP flag notices follow pvp.
CHANNELS = (("death", "Deaths"), ("level", "Level ups"), ("pvp", "PvP alerts"), ("kill", "PvP kills"), ("summary", "Gold summary (on logout)"))
WOW_PARENTS = (r"Program Files (x86)\World of Warcraft", r"Program Files\World of Warcraft",
               r"World of Warcraft", r"Games\World of Warcraft", r"Battle.net\World of Warcraft")


def resource_path(name: str) -> Path:
    """A file shipped next to the package, or inside the bundle when frozen."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / name


def find_wow_dirs(drives: list[str] | None = None) -> list[Path]:
    """Look for WoW Forever install folders (the ones with Screenshots and WTF) in the usual places."""
    if drives is None:
        drives = [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
    found = []
    for drive in drives:
        for parent in WOW_PARENTS:
            base = Path(drive) / parent
            try:
                children = [p for p in base.iterdir() if p.is_dir() and "forever" in p.name.lower()]
            except OSError:
                continue
            found.extend(sorted(children))
    return found


def toml_string(value: str) -> str:
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_config(template: str, webhook_url: str, wow_dir: str, webhooks: dict[str, str] | None = None) -> str:
    """config.toml from the template; webhook_url is the default webhook, webhooks are keyed by event."""
    text = re.sub(r'(?m)^wow_dir\s*=.*$', lambda _: f"wow_dir = {toml_string(wow_dir)}", template, count=1)
    return set_webhooks(text, webhook_url, webhooks or {})


def _section(text: str, name: str) -> re.Match | None:
    return re.search(rf'(?ms)^\[{re.escape(name)}\][^\n]*\n(.*?)(?=^\[|\Z)', text)


def _key_line(key: str) -> re.Pattern:
    # key = value, keeping whatever follows the value (an inline comment)
    return re.compile(rf'''(?m)^({re.escape(key)}\s*=\s*)("(?:[^"\\]|\\.)*"|'[^']*'|[^\s#]+)''')


def set_value(text: str, section: str, key: str, value: str, drop: tuple[str, ...] = ()) -> str:
    """Set key to value (TOML) in [section], keeping comments; lines for the keys in drop are removed."""
    match = _section(text, section)
    if match is None:
        return text.rstrip("\n") + f"\n\n[{section}]\n{key} = {value}\n"
    body = match.group(1)
    for old in drop:
        body = re.sub(rf'(?m)^{re.escape(old)}\s*=.*\n?', "", body)
    if _key_line(key).search(body):
        body = _key_line(key).sub(lambda m: m.group(1) + value, body, count=1)
    else:
        comments = re.match(r'(?:#.*\n)*', body).end()  # after the section's leading comments
        body = body[:comments] + f"{key} = {value}\n" + body[comments:]
    return text[:match.start(1)] + body + text[match.end(1):]


def set_webhook(text: str, event: str, url: str) -> str:
    """Set one event's webhook in config.toml text, keeping everything else (comments included)."""
    return set_value(text, "webhooks", config.NAMES[event], toml_string(url), drop=(event,))


def _drop_top_level_webhook_url(text: str) -> str:
    """Remove the old top-level webhook_url line and the comments right above it."""
    first_table = re.search(r'(?m)^\[', text)
    head, tail = (text[:first_table.start()], text[first_table.start():]) if first_table else (text, "")
    head = re.sub(r'(?m)(?:^#.*\n)*^webhook_url\s*=.*\n(?:[ \t]*\n)?', "", head, count=1)
    return head + tail


def set_webhooks(text: str, webhook_url: str, webhooks: dict[str, str]) -> str:
    """Set the default and per-event webhooks in config.toml text, keeping everything else."""
    text = set_value(_drop_top_level_webhook_url(text), "webhooks", "default", toml_string(webhook_url))
    for event, url in webhooks.items():
        text = set_webhook(text, event, url)
    return text


def upgrade_names(text: str) -> str:
    """Rewrite a config.toml from an older version with the current names, keeping the settings and comments."""
    try:
        old_default = str(tomllib.loads(text).get("webhook_url") or "")
    except tomllib.TOMLDecodeError:
        return text
    text = _drop_top_level_webhook_url(text)
    if old_default:
        text = set_value(text, "webhooks", "default", toml_string(old_default))
    for section, renames in (("webhooks", config.NAMES), ("notify", config.NAMES), ("mentions", {"pvp": "pvp_alerts"})):
        match = _section(text, section)
        if match is None:
            continue
        body = match.group(1)
        for old, new in renames.items():
            if not _key_line(new).search(body):
                body = re.sub(rf'(?m)^{re.escape(old)}(\s*=)', lambda m: new + m.group(1), body, count=1)
        text = text[:match.start(1)] + body + text[match.end(1):]
    return text


def ask_webhook_url(ask: Callable[[str], str] = input) -> str:
    return _ask_url(ask, "Paste the webhook URL (right-click to paste): ")


def _ask_url(ask: Callable[[str], str], prompt: str, default: str = "") -> str:
    while True:
        url = ask(prompt).strip().strip('"')
        if not url and default:
            return default
        if url.startswith(WEBHOOK_PREFIXES):
            return url
        print("  That doesn't look like a Discord webhook URL (it should start with https://discord.com/api/webhooks/).")


def _ask_team_code(ask: Callable[[str], str]) -> tuple[str, dict[str, str]]:
    while True:
        code = ask("  Paste the team code (right-click to paste): ")
        try:
            return teamhooks.read_code(code)
        except teamhooks.TeamHooksError as e:
            print(f"  That didn't work: {e}. Copy the whole code and try again.")


def _ask_webhooks(ask: Callable[[str], str], step: str = "Step 1 of 2") -> tuple[str, dict[str, str]]:
    """Returns the default webhook and the per-event webhooks."""
    print(f"\n{step}: Discord channels")
    print("  1. Paste a team code (your guild posts one in Discord)")
    print("  2. Send everything to one channel of your own")
    print("  3. Use a separate channel of your own for each notification type")
    while (choice := ask("  Enter 1, 2 or 3: ").strip()) not in ("1", "2", "3"):
        pass
    if choice == "1":
        return _ask_team_code(ask)
    print("  In Discord: channel settings (gear) > Integrations > Webhooks > New Webhook > Copy Webhook URL.")
    if choice == "2":
        return _ask_url(ask, "  Paste the webhook URL (right-click to paste): "), {}

    print("  Paste each channel's webhook URL. Press Enter to reuse the previous one.")
    urls: dict[str, str] = {}
    previous = ""
    for event, label in CHANNELS:
        urls[event] = previous = _ask_url(ask, f"  {label}: ", previous)
    return "", urls  # PvP flag notices follow the PvP alerts channel


def add_webhooks(config_path: Path, ask: Callable[[str], str] = input) -> None:
    """For a config.toml without webhooks: ask for them and save, keeping the other settings."""
    print("This version no longer has the team's Discord channels built in.")
    webhook, webhooks = _ask_webhooks(ask, "One question")
    text = upgrade_names(config_path.read_text(encoding="utf-8-sig"))
    config_path.write_text(set_webhooks(text, webhook, webhooks), encoding="utf-8")
    print(f"\nSaved {config_path}\n")


def _ask_wow_dir(ask: Callable[[str], str], candidates: list[Path], step: str = "Step 2 of 2") -> str:
    print(f"\n{step}: WoW Forever folder (the one containing Screenshots and WTF)")
    for i, path in enumerate(candidates, 1):
        print(f"  {i}. {path}")
    hint = f"Enter 1-{len(candidates)} or paste a folder path: " if candidates else "Paste the folder path: "
    while True:
        answer = ask("  " + hint).strip().strip('"')
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return str(candidates[int(answer) - 1])
        if not answer and len(candidates) == 1:
            return str(candidates[0])
        if answer:
            path = Path(answer)
            if path.is_dir():
                if not (path / "WTF").is_dir() and not (path / "Screenshots").is_dir():
                    print("  Note: no WTF or Screenshots folder there yet. Using it anyway.")
                return str(path)
            print("  That folder doesn't exist.")


def run(config_path: Path, ask: Callable[[str], str] = input, candidates: list[Path] | None = None,
        install_addon: Callable[[Path], bool] = addon_install.install_and_report) -> None:
    print("=" * 60)
    print(" ForeverNotify setup")
    print("=" * 60)
    print(f"This creates {config_path}.")
    webhook, webhooks = _ask_webhooks(ask)
    wow_dir = _ask_wow_dir(ask, find_wow_dirs() if candidates is None else candidates)
    template = resource_path("config.example.toml").read_text(encoding="utf-8")
    config_path.write_text(render_config(template, webhook, wow_dir, webhooks), encoding="utf-8")
    print(f"\nSaved {config_path}")
    print("Edit it in Notepad for extra options (@mentions, turning events off...).")
    print("Run 'ForeverNotify.exe setup' to start this setup again.\n")
    install_addon(Path(wow_dir))
    print()
