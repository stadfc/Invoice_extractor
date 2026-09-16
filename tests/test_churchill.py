import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.churchill import ChurchillInvoiceParser
from pipeline import format_for_import
import pandas as pd


class ChurchillParserTests(unittest.TestCase):
    def test_strips_spaces_and_adds_prefix(self):
        self.assertEqual(ChurchillInvoiceParser.format_item_code("WH NSU 1"), "CH-WHNSU1")
        self.assertEqual(ChurchillInvoiceParser.format_item_code("PLULTRB91"), "CH-PLULTRB91")

    def test_splits_three_invoices_and_skips_packing(self):
        lines = [
            "INVOICE FOR PAYMENT PURPOSES",
            "Churchill China (UK) Limited Registered in England and CD2009292980 1/2",
            "PLULTRB91 STONECAST PLUME 6912002310 12 10.5075 126.09",
            "WH NSU 1 WHITE UNHANDLED CONSOMME 6912002310 120 2.7300 327.60",
            "Freight 17.40 17.40",
            "Invoice total",
            "GBP 2737.66",
            "INVOICE PACKING SUMMARY",
            "CD2009292980 1/2",
            "PLULTRB91 STONECAST PLUME 1 0.02 10.34 10.54 0.02 10.34 10.54",
            "INVOICE FOR PAYMENT PURPOSES",
            "Churchill China (UK) Limited Registered in England and CD2009292990 1/2",
            "FSGYEV101 STUDIO PRINTS FUSION GREY 6912002310 24 6.5700 157.68",
            "Invoice total",
            "GBP 573.26",
            "INVOICE FOR PAYMENT PURPOSES",
            "CD2009292991 1/2",
            "FSGYEB221 STUDIO PRINTS FUSION GREY 6912002310 6 8.5233 51.14",
            "Invoice total",
            "GBP 121.88",
        ]
        docs = ChurchillInvoiceParser().parse_documents(lines)
        self.assertEqual([doc.invoice_number for doc in docs], [
            "CD2009292980",
            "CD2009292990",
            "CD2009292991",
        ])
        self.assertEqual(docs[0].products[1][1], "CH-WHNSU1")
        self.assertEqual(docs[0].products[1][2], 120)
        self.assertAlmostEqual(docs[0].freight, 17.40)
        self.assertEqual(len(docs[0].products), 2)
        self.assertEqual(docs[1].products[0][1], "CH-FSGYEV101")
        self.assertAlmostEqual(docs[1].invoice_total, 573.26)
        self.assertAlmostEqual(docs[2].invoice_total, 121.88)
        self.assertEqual(docs[0].currency, "GBP")

    def test_freight_is_spread_into_import_prices(self):
        df = pd.DataFrame(
            [
                ["000", "CH-PLULTRB91", 12, "bowl", 10.5075, 0.0, 126.09],
                ["000", "CH-WHNSU1", 120, "consomme", 2.73, 0.0, 327.60],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = format_for_import(df, pdf_total_amount=471.09, transport_cost=17.40)
        raw = float((result.df["Cena jednostkowa"] * result.df["Ilość"]).sum())
        self.assertTrue(result.matched)
        self.assertAlmostEqual(raw, 471.09, places=4)
