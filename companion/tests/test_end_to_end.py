"""Runs the add-on under Lua 5.1 (tests/lua) and decodes what it drew."""

import json
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from forever_notify import formatting
from forever_notify.app import Notifier
from forever_notify.config import Config
from forever_notify.luasv import parse_saved_variables
from forever_notify.signal_decode import decode_file, parse_payload

REPO = Path(__file__).resolve().parents[2]
LUA = shutil.which("lua5.1") or shutil.which("lua51")


def render(blocks, path, scale=1.0, size=(1920, 1080), seed=1, **save_args):
    """Paint the recorded grid blocks over a noisy 'game' background."""
    rng = random.Random(seed)
    w, h = size
    noise = bytes(rng.randrange(256) for _ in range(w * h * 3 // 64))
    background = Image.frombytes("RGB", (w // 8, h // 8), noise).resize(size, Image.NEAREST)
    image = background.copy()
    pixels = image.load()
    for x, y, bw, bh, r, g, b in blocks:
        colour = (r * 255, g * 255, b * 255)
        for py in range(int(y * scale), int((y + bh) * scale)):
            for px in range(int(x * scale), int((x + bw) * scale)):
                pixels[px, py] = colour
    image.save(path, **save_args)


@unittest.skipUnless(LUA, "lua5.1 not installed")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        result = subprocess.run(
            [LUA, str(REPO / "tests/lua/run_scenario.lua"), str(REPO / "addon/ForeverNotify"), str(cls.tmp)],
            capture_output=True, text=True, cwd=REPO,
        )
        if result.returncode != 0:
            raise AssertionError("Lua scenario failed:\n" + result.stderr + result.stdout)
        cls.signals = json.loads((cls.tmp / "signals.json").read_text())
        cls.sv_text = (cls.tmp / "ForeverNotify.lua").read_text()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_signal_decodes_from_png_and_tga(self):
        self.assertGreaterEqual(len(self.signals), 7)
        for i, record in enumerate(self.signals):
            expected = parse_payload(record["payload"].encode("utf-8"))
            for ext in ("png", "tga"):
                path = self.tmp / f"shot{i}.{ext}"
                render(record["blocks"], path, seed=i)
                self.assertEqual(decode_file(path), expected, f"signal {i} via {ext}")

    def test_decodes_when_blocks_are_scaled(self):
        record = self.signals[0]
        expected = parse_payload(record["payload"].encode("utf-8"))
        for scale in (0.75, 1.5, 2.0):
            path = self.tmp / f"scaled{scale}.png"
            render(record["blocks"], path, scale=scale, size=(2560, 1440))
            self.assertEqual(decode_file(path), expected, f"scale {scale}")

    def test_decodes_at_common_resolutions(self):
        # The add-on draws in physical pixels (6px blocks whatever the resolution or UI scale),
        # so the same blocks land on screens of every size.
        record = max(self.signals, key=lambda r: len(r["blocks"]))  # the biggest grid
        expected = parse_payload(record["payload"].encode("utf-8"))
        width = max(x + w for x, _, w, _, *_ in record["blocks"])
        height = max(y + h for _, y, _, h, *_ in record["blocks"])
        self.assertLessEqual((width, height), (384, 150), "grid fits in a corner of even a 720p screen")
        for size in [(1280, 720), (1366, 768), (1920, 1080), (2560, 1080), (2560, 1440), (3440, 1440),
                     (3840, 2160), (5120, 1440)]:
            path = self.tmp / f"res{size[0]}x{size[1]}.png"
            render(record["blocks"], path, size=size, seed=size[0])
            self.assertEqual(decode_file(path), expected, f"{size[0]}x{size[1]}")

    def test_decodes_with_soft_edges_at_fractional_block_sizes(self):
        # e.g. windowed mode where the window and screen sizes differ: blocks become a fractional
        # number of pixels and smooth scaling blends their edges.
        record = max(self.signals, key=lambda r: len(r["blocks"]))
        expected = parse_payload(record["payload"].encode("utf-8"))
        source = self.tmp / "soft_source.png"
        render(record["blocks"], source)
        for factor in (0.4, 0.6, 0.8, 1.37, 1.75, 2.5):  # 2.4px to 15px blocks
            path = self.tmp / f"soft{factor}.png"
            with Image.open(source) as image:
                image.resize((round(1920 * factor), round(1080 * factor)), Image.BILINEAR).save(path)
            self.assertEqual(decode_file(path), expected, f"x{factor}")

    def test_high_quality_jpeg_still_decodes(self):
        record = self.signals[2]  # PvP alert, a large payload
        path = self.tmp / "shot.jpg"
        render(record["blocks"], path, quality=95)
        self.assertEqual(decode_file(path), parse_payload(record["payload"].encode("utf-8")))

    def test_saved_variables_summary_formats(self):
        data = parse_saved_variables(self.sv_text)
        summary = data["ForeverNotifyDB"]["lastSummary"]
        self.assertEqual(summary["char"], "Thrall")
        self.assertEqual(summary["income"], {"loot": 1234, "quest": 5000, "vendor": 500})
        body = formatting.format_summary(summary)
        fields = {f["name"]: f["value"] for f in body["embeds"][0]["fields"]}
        self.assertEqual(fields["Net change"].split(" (")[0], "+46s 34c")
        self.assertIn("Quests: 50s 0c", fields["Income"])
        self.assertIn("across 2 characters", fields["All characters"])
        self.assertEqual(fields["Deaths"], "3")
        self.assertEqual(fields["Levels"], "23 → 24")

    def test_reload_then_logout_flow(self):
        sent = []
        cfg = Config(webhook_url="https://example.invalid/hook", screenshots_dir=self.tmp,
                     saved_variables_glob="", summary_grace_seconds=30)
        notifier = Notifier(cfg, lambda url, body: sent.append(body))
        data = parse_saved_variables(self.sv_text)
        summary = data["ForeverNotifyDB"]["lastSummary"]

        # A /reload: summary written, then the add-on's RELOAD signal arrives.
        notifier.handle_saved_variables(self.sv_text, now=0)
        notifier.handle_signal({"t": "RELOAD", "c": "Thrall", "r": "Area52", "ts": str(summary["stop"] + 3)})
        notifier.tick(100)
        self.assertEqual(sent, [])

        # A real logout: a later summary and no further signals.
        later = self.sv_text.replace(f'["stop"] = {summary["stop"]}', f'["stop"] = {summary["stop"] + 900}')
        notifier.handle_saved_variables(later, now=200)
        notifier.tick(210)
        self.assertEqual(sent, [])
        notifier.tick(231)
        self.assertEqual(len(sent), 1)
        self.assertIn("gold summary", sent[0]["embeds"][0]["title"])

        # The same file seen again is not re-posted.
        notifier.handle_saved_variables(later, now=300)
        notifier.tick(400)
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
