"""Command-line interface, shared by python -m forever_notify and ForeverNotify.exe."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import app, config, discord, formatting, setup_wizard
from .signal_decode import decode_file

FROZEN = getattr(sys, "frozen", False)  # running as ForeverNotify.exe


def default_config_path() -> Path:
    """config.toml next to the exe when frozen, otherwise in the current folder."""
    return Path(sys.executable).parent / "config.toml" if FROZEN else Path("config.toml")


def send_test(webhook_url: str) -> None:
    body = formatting.format_signal({"t": "TEST", "c": "Companion", "r": "PC", "ts": str(int(time.time()))})
    discord.post(webhook_url, body)


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
    sub.add_parser("test-webhook", help="post a test message to check the webhook works")
    decode_p = sub.add_parser("decode", help="decode signal screenshots and print their payloads")
    decode_p.add_argument("files", nargs="+")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.command == "decode":
        for path in args.files:
            print(path, json.dumps(decode_file(path), ensure_ascii=False))
        return 0

    fresh_setup = False
    if not args.config.exists() and sys.stdin and sys.stdin.isatty():
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

    if args.command == "test-webhook" or fresh_setup:
        try:
            send_test(cfg.webhook_url)
        except RuntimeError as e:
            print(f"Could not post to Discord: {e}", file=sys.stderr)
            return 1
        print("Test message sent. Check your Discord channel.")
        if args.command == "test-webhook":
            return 0

    if getattr(args, "dry_run", False):
        def send(url, body):
            print(json.dumps(body, indent=2, ensure_ascii=False))
    else:
        sender = discord.Sender()
        send = sender.send

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

