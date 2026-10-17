"""Make a team code from the webhooks in a config.toml.

Usage: py -3 make_team_hooks.py [path\\to\\config.toml]   (default: dist\\config.toml)

Prints the code and saves it to dist\\team_code.txt (git-ignored). Post it
somewhere only your team can see; setup asks for it. Only the [webhooks]
section is taken. Each run makes a different code for the same webhooks;
any of them works.
"""

import sys
import tomllib
from pathlib import Path

from forever_notify import config, teamhooks
from forever_notify.setup_wizard import WEBHOOK_PREFIXES

HERE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    source = Path(argv[0]) if argv else HERE / "dist" / "config.toml"
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"Could not read {source}: {e}")
        return 1
    main_url, hooks = config.parse_webhooks(raw)
    named = [("default", main_url)] if main_url else []
    named += [(config.NAMES[event], url) for event, url in hooks.items()]
    bad = [name for name, url in named if not url.startswith(WEBHOOK_PREFIXES)]
    if not named:
        print(f"No webhooks in {source}")
        return 1
    if bad:
        print(f"Not a Discord webhook URL in {source}: {', '.join(bad)}")
        return 1

    code = teamhooks.make_code(main_url, hooks)
    assert teamhooks.read_code(code) == (main_url, hooks)
    target = HERE / "dist" / "team_code.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_text(code + "\n", encoding="utf-8")
    channels = ", ".join(name for name, _ in named)
    print(f"Team code for {channels} from {source}, saved to {target}:\n")
    print(code)
    print("\nAnyone with this code can post to those channels, so share it only with your team.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
