import io
import sys
import unittest
from unittest import mock

from forever_notify import keyhints

ITEMS = [("C", "Change Discord channels"), ("W", "Change WoW folder")]


class KeyHints(unittest.TestCase):
    def test_coloured_line_when_the_console_supports_it(self):
        out = io.StringIO()
        with mock.patch.object(keyhints, "enable_vt", return_value=True), mock.patch.object(sys, "stdout", out):
            keyhints.KeyHints(ITEMS).show()
        self.assertEqual(out.getvalue(), keyhints.render(ITEMS) + "\n")  # an ordinary line: scrolls away
        self.assertIn(f"{keyhints.KEY} C {keyhints.STYLE}", out.getvalue())
        self.assertTrue(out.getvalue().endswith(keyhints.RESET + "\n"))

    def test_plain_line_without_colour(self):
        out = io.StringIO()  # not a console: no ANSI support
        with mock.patch.object(sys, "stdout", out):
            keyhints.KeyHints(ITEMS).show()
        self.assertEqual(out.getvalue(), "[C] Change Discord channels   [W] Change WoW folder\n")

    def test_closed_line(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            keyhints.KeyHints(ITEMS).closed()
        self.assertEqual(out.getvalue(), keyhints.CLOSED + "\n")


if __name__ == "__main__":
    unittest.main()
