"""PyInstaller entry point for ForeverNotify.exe."""

import sys

from forever_notify.cli import frozen_main

sys.exit(frozen_main())
