"""Command-line interface, shared by python -m forever_notify and ForeverNotify.exe."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tomllib
from pathlib import Path

from . import addon_install, app, config, discord, formatting, setup_wizard, updater
from .signal_decode import decode_file

FROZEN = getattr(sys, "frozen", False)  # running as ForeverNotify.exe
BAKED_CONFIG = "baked_config.toml"  # optional personal settings bundled by build_exe.bat


def default_config_path() -> Path:
    """config.toml next to the exe when frozen, otherwise in the current folder."""
    return Path(sys.executable).parent / "config.toml" if FROZEN else Path("config.toml")


def pending_deletes(cfg: config.Config) -> discord.Expiring:
    """Test messages waiting to delete themselves, kept next to config.toml so a restart still removes them."""
    return discord.Expiring(cfg.state_path("pending_deletes.json"))


def post_sample(url: str, body: dict, expiring: discord.Expiring) -> None:
    message_id = discord.post(url, body)
    if message_id:
        expiring.add(url, message_id, body.get(discord.DELETE_AFTER, formatting.TEST_LINGER_SECONDS))


def wait_for_test_cleanup(expiring: discord.Expiring) -> None:
    """For one-off commands: stay open until the test messages have deleted themselves."""
    if not len(expiring):
        return
    print("The test messages delete themselves in about a minute. Keep this window open until then "
          "(Ctrl+C leaves them; ForeverNotify removes them the next time it runs).")
    try:
        expiring.wait_and_delete()
        print("Test messages removed.")
    except KeyboardInterrupt:
        print("\nLeft the test messages for now.")


def send_tests(cfg: config.Config, expiring: discord.Expiring | None = None) -> bool:
    """Post a sample of each notification to its channel. Returns True if all arrived."""
    expiring = expiring if expiring is not None else pending_deletes(cfg)
    ok = True
    samples = formatting.sample_messages({}, cfg.pvp_mention)  # as from character "Companion", realm "PC"
    for event, label in setup_wizard.CHANNELS:
        try:
            post_sample(cfg.webhook_for(event), samples[event], expiring)
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
    if not config.is_webhook_url(url):
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
    sample = formatting.sample_messages({}, cfg.pvp_mention)[channel]
    expiring = pending_deletes(cfg)
    try:
        post_sample(cfg.webhook_for(channel), sample, expiring)
    except RuntimeError as e:
        print(f"Saved, but the sample message didn't reach Discord: {e}", file=sys.stderr)
        return 1
    print(f"Sent a sample {label} message; check that channel. Restart ForeverNotify if it's running.")
    wait_for_test_cleanup(expiring)
    return 0


def confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def build_parser() -> argparse.ArgumentParser:
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
    sub.add_parser("update", help="check for a newer ForeverNotify and install it (asks first)")
    decode_p = sub.add_parser("decode", help="decode signal screenshots and print their payloads")
    decode_p.add_argument("files", nargs="+")
    return parser


def _interactive() -> bool:
    return bool(sys.stdin and sys.stdin.isatty())


def _offer_update(args, restart_args: list[str], **kwargs) -> bool:
    """Offer a newer release. True if the new version has started (in this window), so this copy should end."""
    if not updater.offer_update(args.config.parent, FROZEN, argv=restart_args, **kwargs):
        return False
    if FROZEN:
        updater.exit_now()  # nothing more may run in the replaced exe
    return True


def _prepare_config(args) -> tuple[config.Config, bool] | int:
    """Restore, create or upgrade config.toml as needed and load it: (config, freshly set up) or an exit code."""
    baked = setup_wizard.resource_path(BAKED_CONFIG)
    if not args.config.exists() and args.command != "setup" and baked.is_file():
        args.config.write_bytes(baked.read_bytes())
        print(f"No config found; restored the settings built into this exe to {args.config}.")

    fresh_setup = False
    if args.command == "setup" and args.config.exists():
        if not confirm(f"{args.config} already exists. Replace it with new settings? (y/N): "):
            print("Kept your existing config.")
            return 0
    if args.command == "setup" or (not args.config.exists() and _interactive()):
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
            if not _interactive():
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
    return cfg, fresh_setup


def _watch(args, cfg: config.Config, expiring: discord.Expiring, restart_args: list[str]) -> int:
    """The normal run: offer an update, keep the add-on current, then post events until stopped."""
    dry_run = getattr(args, "dry_run", False)
    if cfg.check_for_updates and not dry_run and _offer_update(args, restart_args, interactive=_interactive()):
        return 0
    if dry_run:
        def send(url, body):
            print(json.dumps(body, indent=2, ensure_ascii=False))
    else:
        send = discord.Sender(expiring=expiring).send  # also removes test messages when their minute is up

    addon_install.sync_and_report(cfg.wow_dir or cfg.screenshots_dir.parent)
    print("ForeverNotify is running. Leave this window open while you play; close it or press Ctrl+C to stop.")
    try:
        app.run(cfg, send)
    except KeyboardInterrupt:
        logging.info("Stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.command == "decode":
        for path in args.files:
            print(path, json.dumps(decode_file(path), ensure_ascii=False))
        return 0

    if FROZEN:
        updater.cleanup_leftovers(Path(sys.executable))  # the previous exe, after an update
    restart_args = ["-c", str(args.config)] + (["-v"] if args.verbose else []) + ["run"]
    if args.command == "update":
        _offer_update(args, restart_args, force=True)
        return 0

    prepared = _prepare_config(args)
    if isinstance(prepared, int):
        return prepared
    cfg, fresh_setup = prepared

    if args.command == "set-webhook":
        return set_webhook(args.config, args.channel, args.url)
    if args.command == "install-addon":
        return 0 if addon_install.install_and_report(cfg.wow_dir or cfg.screenshots_dir.parent) else 1

    expiring = pending_deletes(cfg)
    if args.command == "test-webhook" or fresh_setup:
        ok = send_tests(cfg, expiring)
        if ok:
            print("Check your Discord channels.")
        if args.command == "test-webhook":
            wait_for_test_cleanup(expiring)
            return 0 if ok else 1
        if not ok:
            return 1

    return _watch(args, cfg, expiring, restart_args)


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

