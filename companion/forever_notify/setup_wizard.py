"""First-run setup: ask for the team code or webhooks and the WoW folder, then write config.toml."""

from __future__ import annotations

import re
import string
import sys
from pathlib import Path
from typing import Callable

from . import addon_install, teamhooks

WEBHOOK_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                    "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")
# (config key, label) for each channel the wizard asks about; PvP flag alerts follow pvp.
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
    text = re.sub(r'(?m)^webhook_url\s*=.*$', lambda _: f"webhook_url = {toml_string(webhook_url)}", template, count=1)
    text = re.sub(r'(?m)^wow_dir\s*=.*$', lambda _: f"wow_dir = {toml_string(wow_dir)}", text, count=1)
    if webhooks:
        entries = "".join(f"{event} = {toml_string(url)}\n" for event, url in webhooks.items())
        text = re.sub(r'(?m)^\[webhooks\]\n(?:#.*\n)*', lambda m: m.group(0) + entries, text, count=1)
    return text


def set_webhook(text: str, event: str, url: str) -> str:
    """Set one per-event webhook in config.toml text, keeping everything else (comments included)."""
    line = f"{event} = {toml_string(url)}"
    section = re.search(r'(?ms)^\[webhooks\][^\n]*\n(.*?)(?=^\[|\Z)', text)
    if section is None:
        return text.rstrip("\n") + f"\n\n[webhooks]\n{line}\n"
    body = section.group(1)
    existing = re.compile(rf'(?m)^{re.escape(event)}\s*=.*$')
    if existing.search(body):
        body = existing.sub(lambda _: line, body, count=1)
    else:
        comments = re.match(r'(?:#.*\n)*', body).end()  # after the section's leading comments
        body = body[:comments] + line + "\n" + body[comments:]
    return text[:section.start(1)] + body + text[section.end(1):]


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
    """Returns the main webhook_url and any per-event webhooks that differ from it."""
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
    urls["flag"] = urls["pvp"]
    return urls["death"], {event: url for event, url in urls.items() if url != urls["death"]}


def set_webhooks(text: str, webhook_url: str, webhooks: dict[str, str]) -> str:
    """Set webhook_url and the per-event webhooks in config.toml text, keeping everything else."""
    line = f"webhook_url = {toml_string(webhook_url)}"
    if re.search(r'(?m)^webhook_url\s*=', text):
        text = re.sub(r'(?m)^webhook_url\s*=.*$', lambda _: line, text, count=1)
    else:
        text = line + "\n" + text
    for event, url in webhooks.items():
        text = set_webhook(text, event, url)
    return text


def add_webhooks(config_path: Path, ask: Callable[[str], str] = input) -> None:
    """For a config.toml without webhooks: ask for them and save, keeping the other settings."""
    print("This version no longer has the team's Discord channels built in.")
    webhook, webhooks = _ask_webhooks(ask, "One question")
    text = config_path.read_text(encoding="utf-8-sig")
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
