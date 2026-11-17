import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from parsers.contacto import ContactoInvoiceParser
from pipeline import format_for_import, prices_for_buffer


class ContactoParserTests(unittest.TestCase):
    def test_carriage_is_on_the_invoice_and_not_a_product(self):
        lines = [
            "INVOICE 26-56908 Account 19757",
            "19757 A644 2026-10-22",
            "1068/160 menu / card holder 30 30 2,55 46 41,31",
            "192/260 spatula 26 cm 2 4,95 46 5,35",
            "158,88 16,00 174,88 0 0,00 174,88",
            "Payment due by 2026-11-21 or deduct 2% cash discount if paid by 2026-11-01.",
        ]
        parser = ContactoInvoiceParser()
        rows, total = parser.parse(lines)
        self.assertEqual(parser.invoice_number, "26-56908")
        self.assertEqual(parser.invoice_date, "2026-10-22")
        self.assertAlmostEqual(parser.extracted_transport_cost, 16.00)
        self.assertAlmostEqual(total, 174.88)
        self.assertEqual([row[1] for row in rows], ["CO-1068/160", "CO-192/260"])
        self.assertEqual(rows[0][2], 30)
        self.assertEqual(rows[0][3], "menu / card holder")
        self.assertAlmostEqual(rows[0][6], 41.31)

        frame = pd.DataFrame(
            rows,
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        excel = format_for_import(frame, total, parser.extracted_transport_cost)
        self.assertAlmostEqual(excel.target_grand_total, 62.66)
        self.assertTrue(excel.matched)

    def test_blank_carriage_column_keeps_the_invoice_total(self):
        lines = [
            "INVOICE 26-61728 Account 19757",
            "19757 A5453 2026-11-17",
            "6038/100 vegetable knife 15 15 5,45 46 44,15",
            "7875/070 fridge/freezer thermometer 35 0 4,00 0,00",
            "Warenwert Versandkostenanteil Zwischensumme USt-Satz Umsatzsteuer Rechnungsbetrag",
            "44,15 44,15 0 0,00 44,15",
        ]
        parser = ContactoInvoiceParser()
        rows, total = parser.parse(lines)
        self.assertEqual(parser.invoice_number, "26-61728")
        self.assertAlmostEqual(total, 44.15)
        self.assertAlmostEqual(parser.extracted_transport_cost, 0.0)
        self.assertEqual(rows[0][1], "CO-6038/100")
        self.assertAlmostEqual(rows[0][4], 5.45)
        self.assertEqual(rows[1][2], 0)

        frame = pd.DataFrame(
            rows,
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        priced = prices_for_buffer(frame, total, parser.extracted_transport_cost)
        self.assertAlmostEqual(priced.document_total, 44.15)
        self.assertAlmostEqual(priced.header_discount, 0.0)
        self.assertEqual(len(priced.lines), 1)
        self.assertGreater(priced.lines[0].unit_price, 0)
        self.assertAlmostEqual(priced.lines[0].unit_price * priced.lines[0].qty, 44.15, places=2)


if __name__ == "__main__":
    unittest.main()
