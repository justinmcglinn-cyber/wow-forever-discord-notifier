"""Command-line interface, shared by python -m forever_notify and ForeverNotify.exe."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import addon_install, app, config, discord, formatting, setup_wizard
from .signal_decode import decode_file

FROZEN = getattr(sys, "frozen", False)  # running as ForeverNotify.exe
BAKED_CONFIG = "baked_config.toml"  # optional personal settings bundled by build_exe.bat


def default_config_path() -> Path:
    """config.toml next to the exe when frozen, otherwise in the current folder."""
    return Path(sys.executable).parent / "config.toml" if FROZEN else Path("config.toml")


def channel_events(cfg: config.Config) -> dict[str, list[str]]:
    """Each distinct webhook and the notification types that go to it."""
    channels: dict[str, list[str]] = {}
    for event, label in setup_wizard.CHANNELS:
        channels.setdefault(cfg.webhook_for(event), []).append(label)
    channels.setdefault(cfg.webhook_url, []).append("Tests")
    return channels


def send_tests(cfg: config.Config) -> bool:
    """Post a test message to every configured channel. Returns True if all arrived."""
    ok = True
    for i, (url, labels) in enumerate(channel_events(cfg).items(), 1):
        body = formatting.format_signal({"t": "TEST", "c": "Companion", "r": "PC", "ts": str(int(time.time()))})
        body["embeds"][0]["description"] = "This channel will get: " + ", ".join(labels)
        try:
            discord.post(url, body)
            print(f"Test message sent to channel {i} ({', '.join(labels)}).")
        except RuntimeError as e:
            print(f"Could not post to channel {i} ({', '.join(labels)}): {e}", file=sys.stderr)
            ok = False
    return ok


def confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    parser = argparse.ArgumentParser(prog="ForeverNotify.exe" if FROZEN else "forever_notify", description="WoW Forever → Discord notifier companion")
    parser.add_argument("-c", "--config", type=Path, default=default_config_path(), help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="watch for events and post them to Discord (default)")
    run_p.add_argument("--dry-run", action="store_true", help="print messages instead of posting them")
    sub.add_parser("test-webhook", help="post a test message to each configured channel")
    sub.add_parser("setup", help="run the setup questions again (rewrites config.toml), then start")
    sub.add_parser("install-addon", help="reinstall the add-on in your WoW Interface\\AddOns folder, even if it's newer "
                   "(run does this automatically when needed)")
    decode_p = sub.add_parser("decode", help="decode signal screenshots and print their payloads")
    decode_p.add_argument("files", nargs="+")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.command == "decode":
        for path in args.files:
            print(path, json.dumps(decode_file(path), ensure_ascii=False))
        return 0

    baked = setup_wizard.resource_path(BAKED_CONFIG)
    if not args.config.exists() and args.command != "setup" and baked.is_file():
        args.config.write_bytes(baked.read_bytes())
        print(f"No config found; restored the settings built into this exe to {args.config}.")

    fresh_setup = False
    wants_setup = args.command == "setup" or (not args.config.exists() and sys.stdin and sys.stdin.isatty())
    if args.command == "setup" and args.config.exists():
        if not confirm(f"{args.config} already exists. Replace it with new settings? (y/N): "):
            print("Kept your existing config.")
            return 0
    if wants_setup:
        try:
            setup_wizard.run(args.config)
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled; nothing was saved.", file=sys.stderr)
            return 2
        fresh_setup = True

    try:
        cfg = config.load(args.config)
    except config.ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    wow_dir = cfg.wow_dir or cfg.screenshots_dir.parent
    if args.command == "install-addon":
        return 0 if addon_install.install_and_report(wow_dir) else 1

    if args.command == "test-webhook" or fresh_setup:
        if not send_tests(cfg):
            return 1
        print("Check your Discord channels.")
        if args.command == "test-webhook":
            return 0

    if getattr(args, "dry_run", False):
        def send(url, body):
            print(json.dumps(body, indent=2, ensure_ascii=False))
    else:
        sender = discord.Sender()
        send = sender.send

    addon_install.sync_and_report(wow_dir)
    print("ForeverNotify is running. Leave this window open while you play; close it or press Ctrl+C to stop.")
    try:
        app.run(cfg, send)
    except KeyboardInterrupt:
        logging.info("Stopped.")
    return 0


def frozen_main() -> int:
    """Exe entry point: keep the console open on errors so double-click users can read them."""
    try:
        code = main()
    except KeyboardInterrupt:
        code = 0
    except Exception:
        logging.exception("Unexpected error")
        code = 1
    if code != 0 and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code

