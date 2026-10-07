"""Command-line entry point: python -m forever_notify <command>."""

import sys

from .cli import main

sys.exit(main())
