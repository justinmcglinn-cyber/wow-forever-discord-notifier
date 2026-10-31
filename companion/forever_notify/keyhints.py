"""The highlighted line listing the shortcut keys while ForeverNotify is running.

It is printed when the shortcuts open (when watching starts, and on Space) and
then scrolls away with the log like any other line; a grey line says when they
close. Colour needs a console that understands
ANSI escape codes (Windows 10+ consoles and Windows Terminal do, once
virtual-terminal processing is switched on); otherwise it is printed plain.
"""

from __future__ import annotations

import sys

STYLE = "\x1b[1;97;44m"  # bold bright white on blue
KEY = "\x1b[1;30;103m"   # bold black on bright yellow, for the keys
DIM = "\x1b[90m"         # grey
RESET = "\x1b[0m"
CLOSED = "Shortcuts closed. Press Space to open them."


def enable_vt() -> bool:
    """Switch the Windows console to understand ANSI escape codes. True if they'll work."""
    if not sys.stdout or not sys.stdout.isatty():
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        return False


def render(items: list[tuple[str, str]]) -> str:
    """'[C] Change …' items as one highlighted line: keys in yellow, labels on blue."""
    parts = [f"{KEY} {key} {STYLE} {label}  " for key, label in items]
    return f"{STYLE} " + "".join(parts) + RESET


def plain(items: list[tuple[str, str]]) -> str:
    return "   ".join(f"[{key}] {label}" for key, label in items)


class KeyHints:
    def __init__(self, items: list[tuple[str, str]]):
        self.items = items
        self.colour = enable_vt()

    def show(self) -> None:
        print(render(self.items) if self.colour else plain(self.items))

    def closed(self) -> None:
        print(f"{DIM}{CLOSED}{RESET}" if self.colour else CLOSED)
