import unittest
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.leone import LeoneInvoiceParser
from pipeline import format_for_import


class LeoneParserTests(unittest.TestCase):
    def test_total_is_read_from_the_line_under_the_labels(self):
        lines = [
            "Accompanying Invoice",
            "LEONE SRL - Via Dogana, 25",
            "000965/26B 05/10/2026 050659 1",
            "S0062 Bamboo sushi tray cm 30x11x2,5 - 1 pc CONF 3,00 5,37 38 9,99 NI41",
            "T8442 White melamine square salad bowl - 30x30x11,5 cm - 1 pc PZ 18,00 28,88 53 244,32 NI41",
            "Totale netto merce Totale netto servizi Ulteriori sconti Totale omaggi",
            "1.125,17 0,00 33,76 0,00",
            "Acconti Totale imponibile Totale imposta Totale fattura",
            "0,00 1.091,41 0,00 1.091,41",
            "Abbuoni € Totale da pagare",
            "0,00 1.091,41",
        ]
        parser = LeoneInvoiceParser()
        products, total = parser.parse(lines)
        self.assertEqual(parser.invoice_number, "000965/26B")
        self.assertEqual(parser.invoice_date, "2026-10-05")
        self.assertEqual(len(products), 2)
        self.assertAlmostEqual(total, 1091.41)
        self.assertEqual(products[0][1], "LE-S0062")
        self.assertEqual(products[0][2], 3)
        self.assertAlmostEqual(products[0][6], 9.99)

    def test_further_discount_is_spread_into_import_prices(self):
        df = pd.DataFrame(
            [
                ["000", "LE-A", 1, "goods", 1125.17, 0.0, 1125.17],
            ],
            columns=["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"],
        )
        result = format_for_import(df, pdf_total_amount=1091.41, transport_cost=0.0)
        raw = float((result.df["Cena jednostkowa"] * result.df["Ilość"]).sum())
        self.assertAlmostEqual(result.header_discount, 33.76)
        self.assertTrue(result.matched)
        self.assertAlmostEqual(raw, 1091.41, places=2)
