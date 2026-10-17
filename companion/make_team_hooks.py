"""Make a team code from the webhooks in a config.toml.

Usage: py -3 make_team_hooks.py [path\\to\\config.toml]   (default: dist\\config.toml)

Prints the code and saves it to dist\\team_code.txt (git-ignored). Post it
somewhere only your team can see; setup asks for it. Only webhook_url and
[webhooks] are taken. Each run makes a different code for the same webhooks;
any of them works.
"""

import sys
import tomllib
from pathlib import Path

from forever_notify import teamhooks
from forever_notify.setup_wizard import WEBHOOK_PREFIXES

HERE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    source = Path(argv[0]) if argv else HERE / "dist" / "config.toml"
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"Could not read {source}: {e}")
        return 1
    main_url = str(raw.get("webhook_url", "")).strip()
    hooks = {k: str(v).strip() for k, v in raw.get("webhooks", {}).items() if str(v).strip()}
    bad = [name for name, url in [("webhook_url", main_url), *hooks.items()] if not url.startswith(WEBHOOK_PREFIXES)]
    if bad:
        print(f"Not a Discord webhook URL in {source}: {', '.join(bad)}")
        return 1

    code = teamhooks.make_code(main_url, hooks)
    assert teamhooks.read_code(code) == (main_url, hooks)
    target = HERE / "dist" / "team_code.txt"
    target.parent.mkdir(exist_ok=True)
    target.write_text(code + "\n", encoding="utf-8")
    channels = ", ".join(["default"] + sorted(hooks))
    print(f"Team code for {1 + len(hooks)} webhooks ({channels}) from {source}, saved to {target}:\n")
    print(code)
    print("\nAnyone with this code can post to those channels, so share it only with your team.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
