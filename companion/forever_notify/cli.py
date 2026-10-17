"""Command-line interface, shared by python -m forever_notify and ForeverNotify.exe."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import tomllib
from pathlib import Path

from . import addon_install, app, config, discord, formatting, setup_wizard
from .signal_decode import decode_file

FROZEN = getattr(sys, "frozen", False)  # running as ForeverNotify.exe
BAKED_CONFIG = "baked_config.toml"  # optional personal settings bundled by build_exe.bat


def default_config_path() -> Path:
    """config.toml next to the exe when frozen, otherwise in the current folder."""
    return Path(sys.executable).parent / "config.toml" if FROZEN else Path("config.toml")


def send_tests(cfg: config.Config) -> bool:
    """Post a sample of each notification to its channel. Returns True if all arrived."""
    ok = True
    samples = formatting.sample_messages({"c": "Companion", "r": "PC", "ts": str(int(time.time()))}, cfg.pvp_mention)
    for event, label in setup_wizard.CHANNELS:
        try:
            discord.post(cfg.webhook_for(event), samples[event])
            print(f"Sent a sample {label} message.")
        except RuntimeError as e:
            print(f"Could not post the sample {label} message: {e}", file=sys.stderr)
            ok = False
    return ok


def set_webhook(config_path: Path, channel: str, url: str | None, ask=input) -> int:
    """Change one channel's webhook in config.toml and post a sample there to prove it works."""
    channel = config.ALIASES[channel]
    label = dict(setup_wizard.CHANNELS)[channel]
    if url is None:
        print(f"New webhook for {label}.")
        try:
            url = setup_wizard.ask_webhook_url(ask)
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled; config.toml not changed.", file=sys.stderr)
            return 2
    url = url.strip().strip('"')
    if not url.startswith(setup_wizard.WEBHOOK_PREFIXES):
        print("That doesn't look like a Discord webhook URL (it should start with https://discord.com/api/webhooks/).",
              file=sys.stderr)
        return 2

    text = config_path.read_text(encoding="utf-8-sig")
    for event in (channel, "flag") if channel == "pvp" else (channel,):  # PvP flag alerts share the PvP channel
        text = setup_wizard.set_webhook(text, event, url)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        print(f"Not saved, the result wouldn't load: {e}", file=sys.stderr)
        return 2
    config_path.write_text(text, encoding="utf-8")
    print(f"Saved the {label} webhook to {config_path}.")

    cfg = config.load(config_path)
    sample = formatting.sample_messages({"c": "Companion", "r": "PC", "ts": str(int(time.time()))},
                                        cfg.pvp_mention)[channel]
    try:
        discord.post(cfg.webhook_for(channel), sample)
    except RuntimeError as e:
        print(f"Saved, but the sample message didn't reach Discord: {e}", file=sys.stderr)
        return 1
    print(f"Sent a sample {label} message; check that channel. Restart ForeverNotify if it's running.")
    return 0


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
    sub.add_parser("test-webhook", help="post a sample of each notification to its channel")
    sub.add_parser("setup", help="run the setup questions again (rewrites config.toml), then start")
    sub.add_parser("install-addon", help="reinstall the add-on in your WoW Interface\\AddOns folder, even if it's newer "
                   "(run does this automatically when needed)")
    hook_p = sub.add_parser("set-webhook", help="change one channel's webhook in config.toml, then post a sample there")
    names = [config.NAMES[event] for event, _ in setup_wizard.CHANNELS]
    hook_p.add_argument("channel", choices=names + [event for event, _ in setup_wizard.CHANNELS],
                        metavar="{" + ",".join(names) + "}")
    hook_p.add_argument("url", nargs="?", help="webhook URL (asked for if left out)")
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
        try:
            cfg = config.load(args.config)
        except config.NoWebhookError:
            # A config from a version with the team's webhooks built in: ask for them now.
            if not (sys.stdin and sys.stdin.isatty()):
                raise
            setup_wizard.add_webhooks(args.config)
            cfg = config.load(args.config)
            fresh_setup = True
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; config.toml not changed.", file=sys.stderr)
        return 2
    except config.ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    if args.command == "set-webhook":
        return set_webhook(args.config, args.channel, args.url)

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

