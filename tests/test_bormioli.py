import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.bormioli import BormioliLuigiInvoiceParser


class BormioliParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = BormioliLuigiInvoiceParser()

    def test_all_digit_code_keeps_full_item_number(self):
        self.assertEqual(
            self.parser._format_item_code("10000011688"),
            "BL-10000011688",
        )

    def test_lettered_code_uses_dotted_prefix(self):
        self.assertEqual(
            self.parser._format_item_code("235682MDF121990"),
            "BL-2.35682",
        )
        self.assertEqual(
            self.parser._format_item_code("A10823GTY021990"),
            "BL-A.10823",
        )

    def test_parses_all_digit_and_eur_token_lines(self):
        lines = [
            "10000011688 EXCLUSIVA CARAFFA 1L CT 6 ZCO 216,00 100 ZCO X 353,57 763,71 VE",
            "EAN: 8004360096880 DDT: 80191522 Pce: 216,00",
            "235682MDF121990 BETA DESSERT CT12N20B CT 12 N20B ZCO 96,00 100 ZCO X 86,50 EUR 83,04 VE",
            "EAN: 8004360082173 SO: 69434 Pce: 96,00",
            "184179MU3321990 MISURA P.Z. 1,0 L CT6.MID CT 6 PRET.MID ZCO 198,00 100 ZCO X 188,37 372,97 VE",
            "EAN: 8001133841708 SO: 69434 Pce: 198,00",
        ]
        rows, _total = self.parser.parse(lines)
        codes = [row[1] for row in rows]
        self.assertEqual(codes, ["BL-10000011688", "BL-2.35682", "BL-1.84179"])
        carafe = rows[0]
        self.assertEqual(carafe[2], 216)
        self.assertAlmostEqual(carafe[6], 763.71)
        dessert = rows[1]
        self.assertEqual(dessert[2], 96)
        self.assertAlmostEqual(dessert[6], 83.04)

    def test_epal_is_transport_not_a_product(self):
        lines = [
            "10000011688 EXCLUSIVA CARAFFA 1L CT 6 ZCO 216,00 100 ZCO X 353,57 763,71 VE",
            "EAN: 8004360096880 Pce: 216,00",
            "79136105 PLT EPAL 80X120 OMOLOG PC 9,00 1 PC X 10,00 EUR 90,00 VE",
        ]
        rows, total = self.parser.parse(lines)
        self.assertEqual([row[1] for row in rows], ["BL-10000011688"])
        self.assertAlmostEqual(self.parser.extracted_transport_cost, 90.00)
        self.assertAlmostEqual(total, 853.71)
