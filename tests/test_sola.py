import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.sola import SolaInvoiceParser


class SolaParserTests(unittest.TestCase):
    def test_parses_quantity_with_space_thousands(self):
        lines = [
            "11 123451 1 200 pc. 0,270 324,00",
            "Athene CR all mirror",
            "Coffee Spoon",
            "EAN: 7640159093732",
            "Grand total EUR 6 094,44",
        ]
        rows, total = SolaInvoiceParser().parse(lines)
        self.assertEqual(len(rows), 1)
        ean, code, qty, desc, price, discount, value = rows[0]
        self.assertEqual(code, "SS-123451")
        self.assertEqual(qty, 1200)
        self.assertEqual(ean, "7640159093732")
        self.assertAlmostEqual(price, 0.270)
        self.assertAlmostEqual(value, 324.00)
        self.assertAlmostEqual(total, 6094.44)

    def test_still_parses_plain_qty_and_freight(self):
        lines = [
            "4 107008 300 pc. 1,240 372,00",
            "Cake Fork",
            "EAN: 7640159095224",
            "37 S001 1 75,000 75,00",
            "Freight costs",
        ]
        parser = SolaInvoiceParser()
        rows, _total = parser.parse(lines)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "SS-107008")
        self.assertEqual(rows[0][2], 300)
        self.assertAlmostEqual(parser.extracted_transport_cost, 75.00)
