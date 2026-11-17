import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from parsers.bonna import BonnaInvoiceParser
from pipeline import prices_for_buffer


SAMPLE = [
    "Invoice No: IP-00001368",
    "Invoice Date: 09.10.2026",
    "1st BNC19DZ Banquet Flat Plate 19 cm Pcs 12 1.008 0,97 977,76 EUR 6911.10.00.00.11 Made In Turkey 8697700023761 86977000237616 Kar Porselen",
    "1st S-MT-ARCBNC28CK Arctic Banquet Deep Plate 28 cm 400 cc Pcs 6 30 6,20 185,85 EUR 6911.10.00.00.19 Made In Turkey 8697700163122",
    "1st CUP01 China Cup Pcs 6 10 2,00 20,00 EUR 6911.10.00.00.11 Made In China 8697700000001",
    "1st BOWL02 Other Bowl Pcs 6 4 5,00 20,00 EUR 6912.00.23.10 Made In China 8697700000002",
    "Total : 1.203,61 EUR",
    "45 DAYS",
]


class BonnaParserTests(unittest.TestCase):
    def test_reads_codes_origin_and_customs_code(self):
        parser = BonnaInvoiceParser()
        rows, total = parser.parse(SAMPLE)
        self.assertEqual(parser.invoice_number, "IP-00001368")
        self.assertEqual(parser.invoice_date, "2026-10-09")
        self.assertEqual(parser.payment_days, 45)
        self.assertEqual(rows[0][1], "BN-BNC19DZ")
        self.assertEqual(rows[0][0], "8697700023761")
        self.assertEqual(rows[0][2], 1008)
        self.assertAlmostEqual(rows[0][4], 0.97)
        self.assertAlmostEqual(rows[0][6], 977.76)
        self.assertEqual(rows[1][1], "BN-S-MT-ARCBNC28CK")
        self.assertEqual([item["origin"] for item in parser.line_meta], ["Turkey", "Turkey", "China", "China"])
        self.assertEqual(parser.line_meta[2]["customs"], "6911.10.00.00.11")
        self.assertEqual(parser.line_meta[3]["customs"], "6912.00.23.10")
        self.assertAlmostEqual(total, 1203.61)

    def test_antidumping_duty_is_only_chinese_porcelain(self):
        columns = [
            "EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value",
            "Origin", "Customs_code",
        ]
        df = pd.DataFrame(
            [
                ["1", "BN-TR", 1, "plate", 100.0, 0.0, 100.0, "Turkey", "6911.10.00.00.11"],
                ["2", "BN-CN", 1, "bowl", 100.0, 0.0, 100.0, "China", "6911.10.00.00.11"],
                ["3", "BN-OTHER", 1, "cup", 100.0, 0.0, 100.0, "China", "6912.00.23.10"],
            ],
            columns=columns,
        )
        priced = prices_for_buffer(
            df, pdf_total_amount=300.0, transport_cost=30.0, transport_is_external=True
        )
        by_code = {line.code: line for line in priced.lines}
        self.assertAlmostEqual(by_code["BN-TR"].inne, 10.0)
        self.assertAlmostEqual(by_code["BN-CN"].inne, 10.0)
        self.assertAlmostEqual(by_code["BN-TR"].duty, 0.0)
        self.assertAlmostEqual(by_code["BN-OTHER"].duty, 0.0)
        self.assertAlmostEqual(by_code["BN-CN"].duty, 86.9)
        self.assertAlmostEqual(priced.duty, 86.9)
        document = sum(line.unit_price * line.qty for line in priced.lines)
        self.assertAlmostEqual(document, 300.0, places=2)
