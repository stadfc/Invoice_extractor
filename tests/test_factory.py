import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.factory import InvoiceParserFactory


class FactoryTests(unittest.TestCase):
    def test_available_vendors_lists_every_registered_parser(self):
        vendors = InvoiceParserFactory().available_vendors()
        self.assertEqual(
            vendors,
            [
                "APS",
                "Leone",
                "Sola Swiss",
                "Contacto",
                "Bormioli Luigi",
                "Pintinox",
                "Churchill",
            ],
        )
