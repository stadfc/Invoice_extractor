import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.aps import APSInvoiceParser
from pipeline import format_for_import
import pandas as pd


class APSParserTests(unittest.TestCase):
    def test_pads_short_article_numbers_and_reads_discount(self):
        lines = [
            "4004133000223 22 10 card holder, 18 pcs. set 13,30 50,00% 66,50",
            "4004133811010 81101 4 GN 1/1 container 5,70 22,80",
            "amount postage freight packaging amount final amount",
            "113,15 0,00 0,00 0,00 113,15 EUR 113,15",
        ]
        rows, total = APSInvoiceParser().parse(lines)
        self.assertEqual(rows[0][1], "AP-00022")
        self.assertEqual(rows[0][2], 10)
        self.assertAlmostEqual(rows[0][5], 50.0)
        self.assertEqual(rows[1][1], "AP-81101")
        self.assertAlmostEqual(rows[1][5], 0.0)
        self.assertAlmostEqual(total, 113.15)

    def test_header_discount_spreads_sonderrabatt_into_unit_prices(self):
        df = pd.DataFrame(
            [
                ["4004133000223", "AP-00022", 10, "card holder", 13.30, 50.0, 66.50],
                ["4004133115408", "AP-11540", 10, "display", 200.00, 50.0, 1000.00],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = format_for_import(df, pdf_total_amount=1013.18, transport_cost=0.0)
        raw = float((result.df["Cena jednostkowa"] * result.df["Ilość"]).sum())
        self.assertAlmostEqual(result.header_discount, 53.32)
        self.assertTrue(result.matched)
        self.assertAlmostEqual(raw, 1013.18, places=4)
