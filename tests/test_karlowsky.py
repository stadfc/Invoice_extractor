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

    def test_factory_detects_karlowsky(self):
        parser = InvoiceParserFactory().get_parser_for_text(
            "\n".join(SAMPLE_LINES)
        )
        self.assertIsNotNone(parser)
        self.assertEqual(parser.vendor_name, "Karlowsky")
