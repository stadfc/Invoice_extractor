import unittest
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import (
    ParseResult,
    _spread_pack_freight,
    drop_zero_rows,
    format_for_import,
    format_money,
    needs_manual_transport,
    prices_for_buffer,
)


class PipelineTests(unittest.TestCase):
    def test_drop_zero_rows_keeps_positive_lines(self):
        df = pd.DataFrame(
            [
                ["1", "A-1", 2, "fork", 10.0, 0.0, 20.0],
                ["2", "A-2", 0, "zero qty", 10.0, 0.0, 0.0],
                ["3", "A-3", 1, "zero value", 0.0, 0.0, 0.0],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        cleaned = drop_zero_rows(df)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned.iloc[0]["Product_code"], "A-1")

    def test_format_for_import_matches_target_total(self):
        df = pd.DataFrame(
            [
                ["111", "CODE-1", 2, "item one", 10.0, 0.0, 20.00],
                ["222", "CODE-2", 1, "item two", 5.0, 0.0, 5.00],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = format_for_import(df, pdf_total_amount=25.00, transport_cost=0.0)
        self.assertEqual(list(result.df.columns), ["Kod", "Ilość", "Cena jednostkowa"])
        self.assertEqual(len(result.df), 2)
        self.assertTrue(result.matched)
        self.assertEqual(result.target_grand_total, 25.00)
        self.assertEqual(result.simulated_sum, 25.00)
        raw = float((result.df["Cena jednostkowa"] * result.df["Ilość"]).sum())
        self.assertEqual(round(raw, 2), 25.00)
        self.assertAlmostEqual(raw, 25.00, places=4)

    def test_sumproduct_matches_invoice_when_qty_has_thousands(self):
        df = pd.DataFrame(
            [
                ["1", "SS-A", 60, "fork", 1.47, 0.0, 88.20],
                ["2", "SS-123453", 1200, "spoon", 0.27, 0.0, 324.00],
                ["3", "SS-B", 12, "ladle", 3.12, 0.0, 37.44],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = format_for_import(df, pdf_total_amount=449.64, transport_cost=75.00)
        raw = float((result.df["Cena jednostkowa"] * result.df["Ilość"]).sum())
        self.assertEqual(result.target_grand_total, 524.64)
        self.assertTrue(result.matched)
        self.assertEqual(round(raw, 2), 524.64)
        self.assertAlmostEqual(raw, 524.64, places=4)

    def test_header_discount_is_spread_into_unit_prices(self):
        df = pd.DataFrame(
            [
                ["111", "CODE-1", 1, "item", 100.0, 0.0, 100.00],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = format_for_import(df, pdf_total_amount=90.00, transport_cost=0.0)
        self.assertEqual(result.header_discount, 10.00)
        self.assertTrue(result.matched)
        self.assertEqual(result.df.iloc[0]["Cena jednostkowa"], 90.0)

    def test_leone_without_transport_is_flagged(self):
        self.assertTrue(needs_manual_transport("Leone", 0.0))
        self.assertFalse(needs_manual_transport("Leone", 12.5))
        self.assertFalse(needs_manual_transport("APS", 0.0))

    def test_carriage_printed_on_the_invoice_is_inside_the_unit_price(self):
        df = pd.DataFrame(
            [
                ["1", "CO-A", 2, "board", 10.0, 0.0, 20.00],
                ["2", "CO-B", 1, "measure", 5.0, 0.0, 5.00],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = prices_for_buffer(
            df, pdf_total_amount=41.00, transport_cost=16.0, transport_is_external=False
        )
        document = sum(line.unit_price * line.qty for line in result.lines)
        inne = sum(line.inne * line.qty for line in result.lines)
        self.assertAlmostEqual(result.document_total, 41.0)
        self.assertAlmostEqual(document, 41.0, places=2)
        self.assertAlmostEqual(inne, 0.0, places=2)
        self.assertTrue(result.matched)

    def test_external_transport_stays_off_the_document(self):
        df = pd.DataFrame(
            [
                ["1", "LE-A", 1, "tray", 80.0, 0.0, 80.00],
                ["2", "LE-B", 1, "bowl", 20.0, 0.0, 20.00],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = prices_for_buffer(
            df, pdf_total_amount=90.00, transport_cost=10.0, transport_is_external=True
        )
        document = sum(line.unit_price * line.qty for line in result.lines)
        inne = sum(line.inne * line.qty for line in result.lines)
        self.assertAlmostEqual(result.header_discount, 10.0)
        self.assertAlmostEqual(result.document_total, 90.0)
        self.assertAlmostEqual(document, 90.0, places=2)
        self.assertAlmostEqual(inne, 10.0, places=2)
        self.assertTrue(result.matched)

    def test_pack_freight_lowers_the_first_warehouse_value(self):
        columns = ["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"]
        first = ParseResult(
            vendor="Churchill",
            pdf_total_amount=130.0,
            transport_cost=30.0,
            transport_is_external=False,
            rows=pd.DataFrame([["0", "CH-A", 1, "bowl", 100.0, 0.0, 100.0]], columns=columns),
            invoice_number="CD1",
        )
        second = ParseResult(
            vendor="Churchill",
            pdf_total_amount=100.0,
            transport_cost=0.0,
            transport_is_external=False,
            rows=pd.DataFrame([["0", "CH-B", 1, "plate", 100.0, 0.0, 100.0]], columns=columns),
            invoice_number="CD2",
        )
        spread = _spread_pack_freight([first, second])
        self.assertAlmostEqual(spread[0].warehouse_transport, 15.0)
        self.assertAlmostEqual(spread[1].warehouse_transport, 15.0)
        priced = [
            prices_for_buffer(
                item.rows,
                item.pdf_total_amount,
                item.transport_cost,
                transport_is_external=item.transport_is_external,
                warehouse_transport=item.warehouse_transport,
            )
            for item in spread
        ]
        document = [sum(line.unit_price * line.qty for line in item.lines) for item in priced]
        warehouse = [sum((line.unit_price + line.inne) * line.qty for line in item.lines) for item in priced]
        self.assertAlmostEqual(document[0], 130.0, places=2)
        self.assertAlmostEqual(document[1], 100.0, places=2)
        self.assertAlmostEqual(warehouse[0], 115.0, places=2)
        self.assertAlmostEqual(warehouse[1], 115.0, places=2)
        self.assertLess(warehouse[0], document[0])
        self.assertGreater(warehouse[1], document[1])

    def test_format_money_uses_invoice_currency_symbol(self):
        self.assertEqual(format_money(2737.66, "GBP"), "2737.66 £")
        self.assertEqual(format_money(113.15, "EUR"), "113.15 €")


if __name__ == "__main__":
    unittest.main()
