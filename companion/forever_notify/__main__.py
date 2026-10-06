"""Command-line entry point: python -m forever_notify <command>."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from . import app, config, discord, formatting
from .signal_decode import decode_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forever_notify", description="WoW Forever → Discord notifier companion")
    parser.add_argument("-c", "--config", default="config.toml", help="path to config.toml")
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

    try:
        cfg = config.load(args.config)
    except config.ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    if args.command == "test-webhook":
        body = formatting.format_signal({"t": "TEST", "c": "Companion", "r": "PC", "ts": str(int(time.time()))})
        discord.post(cfg.webhook_url, body)
        print("Test message sent.")
        return 0

    if getattr(args, "dry_run", False):
        def send(url, body):
            print(json.dumps(body, indent=2, ensure_ascii=False))
    else:
        sender = discord.Sender()
        send = sender.send

    try:
        app.run(cfg, send)
    except KeyboardInterrupt:
        logging.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
