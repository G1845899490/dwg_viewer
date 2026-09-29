from __future__ import annotations

import unittest

from dwg_viewer.core.coordinate import ParseError, parse_bounds, parse_point


class ParsePointTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_point("1.5, 2.5"), (1.5, 2.5))
        self.assertEqual(parse_point("(1.5, 2.5)"), (1.5, 2.5))
        self.assertEqual(parse_point("  -3  4  "), (-3.0, 4.0))
        self.assertEqual(parse_point("1e2, -2.5e-1"), (100.0, -0.25))

    def test_fullwidth(self):
        self.assertEqual(parse_point("1.5，2.5"), (1.5, 2.5))
        self.assertEqual(parse_point("（1.5，2.5）"), (1.5, 2.5))

    def test_wrong_count(self):
        with self.assertRaises(ParseError):
            parse_point("1, 2, 3")


class ParseBoundsTests(unittest.TestCase):
    def test_comma_form(self):
        self.assertEqual(parse_bounds("0, 10, 20, 0"), (0.0, 10.0, 20.0, 0.0))

    def test_paren_pair_form(self):
        self.assertEqual(parse_bounds("(0, 0) (20, 10)"), (0.0, 10.0, 20.0, 0.0))
        self.assertEqual(parse_bounds("(20, 10) (0, 0)"), (0.0, 10.0, 20.0, 0.0))

    def test_wrong_count(self):
        with self.assertRaises(ParseError):
            parse_bounds("1, 2, 3")


if __name__ == "__main__":
    unittest.main()
