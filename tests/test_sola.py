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

    def test_set_unit_spaced_value_and_zero_pallet(self):
        lines = [
            "Invoice 261505631",
            "Document date : 08. 10. 2026",
            "1 118792 1 Set 27,162 27,16",
            "Basic Country II Lunasol",
            "EAN: 7640159097396",
            "6 123452 1 200 pc. 1,000 1 200,00",
            "Athene CR all mirror",
            "EAN: 7640159093725",
            "9 900079 1 pc. 0,000 0,00",
            "Disposable pallet",
            "Grand total EUR 2 675,33",
        ]
        parser = SolaInvoiceParser()
        rows, total = parser.parse(lines)
        self.assertEqual(parser.invoice_number, "261505631")
        self.assertEqual(parser.invoice_date, "2026-10-08")
        self.assertEqual([row[1] for row in rows], ["SS-118792", "SS-123452"])
        self.assertEqual(rows[0][2], 1)
        self.assertAlmostEqual(rows[0][4], 27.162)
        self.assertAlmostEqual(rows[0][6], 27.16)
        self.assertEqual(rows[1][2], 1200)
        self.assertAlmostEqual(rows[1][6], 1200.00)
        self.assertAlmostEqual(total, 2675.33)
