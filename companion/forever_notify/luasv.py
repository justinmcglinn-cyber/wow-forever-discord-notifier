"""Minimal parser for WoW SavedVariables files (Lua table literals)."""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+|--[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf\b|nan\b))
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[{}\[\]=,;])
    """,
    re.VERBOSE | re.DOTALL,
)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
            "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


class LuaParseError(ValueError):
    pass


def _unescape(body: str) -> str:
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out += c.encode("utf-8")
            i += 1
            continue
        nxt = body[i + 1]
        if nxt.isdigit():
            digits = re.match(r"\d{1,3}", body[i + 1:]).group(0)
            out.append(int(digits) & 0xFF)
            i += 1 + len(digits)
        else:
            out += _ESCAPES.get(nxt, nxt).encode("utf-8")
            i += 2
    return out.decode("utf-8", errors="replace")


def _tokenize(text: str):
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise LuaParseError(f"unexpected character {text[pos]!r} at offset {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            yield kind, m.group(kind)


class _Parser:
    def __init__(self, text: str):
        self.tokens = list(_tokenize(text))
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if tok[0] is None or (value is not None and tok[1] != value):
            raise LuaParseError(f"expected {value!r}, got {tok[1]!r}")
        self.i += 1
        return tok

    def value(self) -> Any:
        kind, text = self.take()
        if kind == "string":
            return _unescape(text[1:-1])
        if kind == "number":
            if text.lower().lstrip("-").startswith("0x"):
                return int(text, 16)
            if text in ("inf", "-inf", "nan"):
                return float(text)
            num = float(text)
            return int(num) if num.is_integer() and "." not in text and "e" not in text.lower() else num
        if kind == "name":
            if text == "true":
                return True
            if text == "false":
                return False
            if text == "nil":
                return None
            raise LuaParseError(f"unexpected name {text!r}")
        if text == "{":
            return self.table()
        raise LuaParseError(f"unexpected token {text!r}")

    def table(self) -> dict:
        result: dict = {}
        index = 1
        while self.peek()[1] != "}":
            if self.peek()[1] == "[":
                self.take("[")
                key = self.value()
                self.take("]")
                self.take("=")
                result[key] = self.value()
            elif self.peek()[0] == "name" and self.i + 1 < len(self.tokens) and self.tokens[self.i + 1][1] == "=":
                key = self.take()[1]
                self.take("=")
                result[key] = self.value()
            else:
                result[index] = self.value()
                index += 1
            if self.peek()[1] in (",", ";"):
                self.take()
        self.take("}")
        return result


def parse_saved_variables(text: str) -> dict[str, Any]:
    """Parse `Name = value` assignments from a SavedVariables file."""
    parser = _Parser(text)
    out: dict[str, Any] = {}
    while parser.peek()[0] is not None:
        kind, name = parser.take()
        if kind != "name":
            raise LuaParseError(f"expected variable name, got {name!r}")
        parser.take("=")
        out[name] = parser.value()
    return out
