"""Decode the ForeverNotify signal grid from a WoW screenshot.

Layout (must match addon/ForeverNotify/Signal.lua):
  row 0      calibration: COLUMNS blocks alternating white/black
  rows 1..n  data, 3 bits per block (red=4, green=2, blue=1), row-major
Data bytes: b"FN" version len_hi len_lo payload... fletcher16_hi fletcher16_lo
(checksum covers version through payload).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

COLUMNS = 64
MAGIC = b"FN"
VERSION = 1
HEADER_LEN = 5
MAX_PAYLOAD = 4096
CALIBRATION_EDGES = 16


def fletcher16(data: bytes) -> tuple[int, int]:
    s1 = s2 = 0
    for b in data:
        s1 = (s1 + b) % 255
        s2 = (s2 + s1) % 255
    return s2, s1


def _bright(p) -> bool:
    return (p[0] + p[1] + p[2]) > 382


def _block_size(px, width: int, height: int) -> float | None:
    """Measure block size from the white/black calibration row."""
    if width < 64 or height < 4:
        return None
    y = 1
    if not (_bright(px[0, y]) and _bright(px[1, y])):
        return None
    # Use every white/black edge in the row (up to COLUMNS - 1): measuring over the whole row keeps
    # the error tiny at fractional block sizes, where it would otherwise add up across 64 columns.
    edges = []
    state = True
    for x in range(1, min(width, COLUMNS * 64)):
        b = _bright(px[x, y])
        if b != state:
            edges.append(x)
            state = b
            if len(edges) == COLUMNS - 1:
                break
    if len(edges) < CALIBRATION_EDGES:
        return None
    size = edges[-1] / len(edges)
    if not 2 <= size <= 64:
        return None
    tolerance = max(1.5, size * 0.25)
    for k, edge in enumerate(edges, start=1):
        if abs(edge - k * size) > tolerance:
            return None
    return size


def _sample(px, x: float, y: float, size: float) -> tuple[int, int, int]:
    """Average the pixels around a block centre."""
    r = 1 if size >= 4 else 0
    cx, cy = int(x), int(y)
    acc = [0, 0, 0]
    n = 0
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            p = px[cx + dx, cy + dy]
            acc[0] += p[0]
            acc[1] += p[1]
            acc[2] += p[2]
            n += 1
    return acc[0] // n, acc[1] // n, acc[2] // n


class _Grid:
    def __init__(self, px, size: float, width: int, height: int):
        self.px, self.size, self.width, self.height = px, size, width, height

    def block(self, col: int, row: int) -> tuple[int, int, int] | None:
        x = (col + 0.5) * self.size
        y = (row + 0.5) * self.size
        if x + 2 >= self.width or y + 2 >= self.height:
            return None
        return _sample(self.px, x, y, self.size)

    def calibration_ok(self) -> bool:
        for col in range(COLUMNS):
            p = self.block(col, 0)
            if p is None:
                return False
            if col % 2 == 0 and min(p) < 160:
                return False
            if col % 2 == 1 and max(p) > 95:
                return False
        return True

    def read_bytes(self, count: int) -> bytes | None:
        blocks = (count * 8 + 2) // 3
        bits = []
        for i in range(blocks):
            p = self.block(i % COLUMNS, 1 + i // COLUMNS)
            if p is None:
                return None
            bits.extend((p[0] > 127, p[1] > 127, p[2] > 127))
        out = bytearray()
        for i in range(count):
            v = 0
            for bit in bits[i * 8:(i + 1) * 8]:
                v = (v << 1) | bit
            out.append(v)
        return bytes(out)


def decode_bytes(image: Image.Image) -> bytes | None:
    """Return the payload bytes carried by the image, or None if it has no valid grid."""
    rgb = image.convert("RGB")
    px = rgb.load()
    width, height = rgb.size
    size = _block_size(px, width, height)
    if size is None:
        return None
    grid = _Grid(px, size, width, height)
    if not grid.calibration_ok():
        return None
    header = grid.read_bytes(HEADER_LEN)
    if header is None or header[:2] != MAGIC or header[2] != VERSION:
        return None
    length = header[3] * 256 + header[4]
    if length > MAX_PAYLOAD:
        return None
    data = grid.read_bytes(HEADER_LEN + length + 2)
    if data is None:
        return None
    body, checksum = data[2:-2], data[-2:]
    if fletcher16(body) != (checksum[0], checksum[1]):
        return None
    return data[HEADER_LEN:-2]


def parse_payload(raw: bytes) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        key, sep, value = line.partition("=")
        if sep:
            payload[key] = value
    return payload


def decode_file(path: str | Path) -> dict[str, str] | None:
    with Image.open(path) as image:
        image.load()
        raw = decode_bytes(image)
    return None if raw is None else parse_payload(raw)
