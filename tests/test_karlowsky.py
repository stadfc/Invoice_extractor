import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.karlowsky import KarlowskyInvoiceParser
from parsers.factory import InvoiceParserFactory


SAMPLE_LINES = """
Invoice
MARMAT Mateusz
Invoice no.: 246239
Date: 09.09.2026
pos. article/colour quantity total price total
[EUR] [EUR]
10 PF 6 Polo de travail pour femmeModern-Flair, 51% GRS Recycled Post-Consumer Polyester /
47% Cotton / 2% Elastane
Customs tariff no: 61062000
PF 6/01 black S L 2 11,19 22,38
1 1
Country of origin:Pakistan
Weight: 0,449 kg
Tabulator
PF 6/70 fuchsia XL 2XL 2 11,19 22,38
1 1
Country of origin:Pakistan
Weight: 0,551 kg
Tabulator
PF 6/74 pacific blue XL 1 11,19 11,19
1
Country of origin:Pakistan
Weight: 0,263 kg
Tabulator
50 TM 9 T-shirt de travail pour hommeCasual-Flair
TM 9/74 pacific blue S M L 3 6,52 19,56
1 1 1
TM 9/76 royal blue S M L XL 4 6,52 26,08
1 1 1 1
70 BPF 3 Ladies' Workwear Polo Shirt Basic
BPF 3/06 blue S M L XL 2XL 6 11,02 66,12
1 1 1 1 2
total amount: 18 167,71
order 358529 postage: 12,65
plus 0,0% VAT of: 180,36 0,00
amount: 180,36
payment notification, please send it to invoice@karlowsky.de.
""".strip().splitlines()


class KarlowskyParserTests(unittest.TestCase):
    def test_format_strips_spaces_and_leading_color_zeros(self):
        self.assertEqual(
            KarlowskyInvoiceParser.format_item_code("PF 6", "01", "S"),
            "KAR-PF6/1/S",
        )
        self.assertEqual(
            KarlowskyInvoiceParser.format_item_code("PF 6", "70", "XL"),
            "KAR-PF6/70/XL",
        )
        self.assertEqual(
            KarlowskyInvoiceParser.format_item_code("BPF 3", "06", "2XL"),
            "KAR-BPF3/6/2XL",
        )
        self.assertEqual(
            KarlowskyInvoiceParser.format_item_code("HM 12", "03", "46/S"),
            "KAR-HM12/3/46/s",
        )

    def test_splits_colour_and_size_into_separate_rows(self):
        parser = KarlowskyInvoiceParser()
        rows, total = parser.parse(SAMPLE_LINES)
        codes = [row[1] for row in rows]
        qtys = {row[1]: row[2] for row in rows}
        self.assertEqual(
            codes,
            [
                "KAR-PF6/1/S",
                "KAR-PF6/1/L",
                "KAR-PF6/70/XL",
                "KAR-PF6/70/2XL",
                "KAR-PF6/74/XL",
                "KAR-TM9/74/S",
                "KAR-TM9/74/M",
                "KAR-TM9/74/L",
                "KAR-TM9/76/S",
                "KAR-TM9/76/M",
                "KAR-TM9/76/L",
                "KAR-TM9/76/XL",
                "KAR-BPF3/6/S",
                "KAR-BPF3/6/M",
                "KAR-BPF3/6/L",
                "KAR-BPF3/6/XL",
                "KAR-BPF3/6/2XL",
            ],
        )
        self.assertEqual(qtys["KAR-PF6/1/S"], 1)
        self.assertEqual(qtys["KAR-PF6/1/L"], 1)
        self.assertEqual(qtys["KAR-PF6/74/XL"], 1)
        self.assertEqual(qtys["KAR-BPF3/6/2XL"], 2)
        self.assertEqual(sum(row[2] for row in rows), 18)
        self.assertAlmostEqual(sum(row[6] for row in rows), 167.71, places=2)
        self.assertAlmostEqual(total, 180.36)
        self.assertAlmostEqual(parser.extracted_transport_cost, 12.65)
        self.assertEqual(parser.invoice_number, "246239")

    def test_numeric_sizes_wrap_onto_the_next_line(self):
        lines = """
Invoice no.: 249125
Date: 16.10.2026
RCJF 15/01 black 36 38 40 42 44 46 48 50 10 33,59 335,90
1 1 1 1 1 1 1 1
52 54
1 1
RCJM 20/01 black 46 48 50 52 54 56 60 7 33,59 235,13
1 1 1 1 1 1 1
RCHF 4/01 black 40 42 44 46 48 50 52 54 8 32,57 260,56
1 1 1 1 1 1 1 1
amount: 814,96
""".strip().splitlines()
        parser = KarlowskyInvoiceParser()
        rows, total = parser.parse(lines)
        codes = [row[1] for row in rows]
        self.assertEqual(parser.invoice_date, "2026-10-16")
        self.assertEqual(codes[:2], ["KAR-RCJF15/1/36", "KAR-RCJF15/1/38"])
        self.assertEqual(codes[8:10], ["KAR-RCJF15/1/52", "KAR-RCJF15/1/54"])
        self.assertIn("KAR-RCJM20/1/60", codes)
        self.assertIn("KAR-RCHF4/1/40", codes)
        self.assertEqual(sum(row[2] for row in rows), 25)
        self.assertAlmostEqual(sum(row[6] for row in rows), 814.96, places=2)
        self.assertAlmostEqual(rows[0][4], 32.9176, places=4)
        self.assertAlmostEqual(total, 814.96)

    def test_short_leg_size_with_a_slash_is_its_own_code(self):
        lines = """
Invoice no.: 251655
Date: 16.11.2026
HM 12/03 white 46/s 3 25,30 75,90
3
JM 24/16 vintage black 54 2 29,33 58,66
2
JM 25/03 white 56 2 36,78 73,56
2
JM 25/10 navy 56 1 39,85 39,85
1
postage: 12,65
amount: 260,62
""".strip().splitlines()
        parser = KarlowskyInvoiceParser()
        rows, total = parser.parse(lines)
        codes = [row[1] for row in rows]
        self.assertEqual(
            codes,
            [
                "KAR-HM12/3/46/s",
                "KAR-JM24/16/54",
                "KAR-JM25/3/56",
                "KAR-JM25/10/56",
            ],
        )
        self.assertEqual(rows[0][2], 3)
        self.assertAlmostEqual(rows[0][4], 25.30, places=2)
        self.assertAlmostEqual(sum(row[6] for row in rows), 247.97, places=2)
        self.assertAlmostEqual(total, 260.62)
        self.assertAlmostEqual(parser.extracted_transport_cost, 12.65)

    def test_factory_detects_karlowsky(self):
        parser = InvoiceParserFactory().get_parser_for_text(
            "\n".join(SAMPLE_LINES)
        )
        self.assertIsNotNone(parser)
        self.assertEqual(parser.vendor_name, "Karlowsky")
