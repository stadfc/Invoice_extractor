import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.mesa import MesaInvoiceParser


SAMPLE = [
    "13 1027/26001350 21/10/2026 1/3",
    "1 FF0251982182 Urban/Uno Plate 28 Speckle Chalk Tela 150 UN 0 % 3.1100 0.00% 466.50",
    "# 1 Batch 2603034 Quantity 39",
    "13 1027/26001350 21/10/2026 2/3",
    "9 FF0891985179 Coupe Pasta Bowl 27 Speckle Chalk Tela 252 UN 0 % 4.3500 0.00% 1,096.20",
    "Total EUR 6,816.30 0.00 Total EUR 6,816.30",
    "Duplicate",
    "13 1027/26001350 21/10/2026 1/3",
    "1 FF0251982182 Urban/Uno Plate 28 Speckle Chalk Tela 150 UN 0 % 3.1100 0.00% 466.50",
    "13 1027/26001350 21/10/2026 1/3",
    "1 FF0251982182 Urban/Uno Plate 28 Speckle Chalk Tela 150 UN 0 % 3.1100 0.00% 466.50",
]


class MesaParserTests(unittest.TestCase):
    def test_reads_the_first_copy_only(self):
        parser = MesaInvoiceParser()
        rows, total = parser.parse(SAMPLE)
        self.assertEqual(parser.invoice_number, "1027/26001350")
        self.assertEqual(parser.invoice_date, "2026-10-21")
        self.assertEqual([row[1] for row in rows], ["KJ-FF0251982182", "KJ-FF0891985179"])
        self.assertEqual(rows[0][2], 150)
        self.assertEqual(rows[0][3], "Urban/Uno Plate 28 Speckle Chalk Tela")
        self.assertAlmostEqual(rows[0][4], 3.11)
        self.assertAlmostEqual(rows[0][6], 466.50)
        self.assertEqual(rows[1][2], 252)
        self.assertAlmostEqual(rows[1][6], 1096.20)
        self.assertAlmostEqual(total, 6816.30)
