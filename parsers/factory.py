from parsers.base import InvoiceParserStrategy
from parsers.aps import APSInvoiceParser
from parsers.leone import LeoneInvoiceParser
from parsers.sola import SolaInvoiceParser
from parsers.contacto import ContactoInvoiceParser
from parsers.bormioli import BormioliLuigiInvoiceParser
from parsers.pintinox import PintinoxInvoiceParser
from parsers.churchill import ChurchillInvoiceParser

class InvoiceParserFactory:
    """Fabryka odpowiedzialna za automatyczny dobór odpowiedniego parsera."""

    def __init__(self):
        self._parsers: list[InvoiceParserStrategy] = [
            APSInvoiceParser(),
            LeoneInvoiceParser(),
            SolaInvoiceParser(),
            ContactoInvoiceParser(),
            BormioliLuigiInvoiceParser(),
            PintinoxInvoiceParser(),
            ChurchillInvoiceParser(),
        ]

    def list_parsers(self) -> list[InvoiceParserStrategy]:
        return list(self._parsers)

    def available_vendors(self) -> list[str]:
        return [parser.vendor_name for parser in self._parsers]

    def get_parser_for_text(self, full_text: str) -> InvoiceParserStrategy:
        full_text_lower = full_text.lower()
        for parser in self._parsers:
            if any(kw.lower() in full_text_lower for kw in parser.keywords):
                return parser
        return None