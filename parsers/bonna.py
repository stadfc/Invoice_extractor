import re

from parsers.base import InvoiceParserStrategy


class BonnaInvoiceParser(InvoiceParserStrategy):
    """Kar Porselen commercial invoice. The Symfonia document is an import DIM."""

    keywords = ["kar porselen", "bonna"]
    vendor_name = "Bonna"
    currency = "EUR"

    _product_re = re.compile(
        r"^\d+(?:st|nd|rd|th)\s+(\S+)\s+(.+?)\s+Pcs\s+\d+\s+([\d.]+)\s+"
        r"(\d+,\d+)\s+([\d.]+,\d+)\s+[A-Z]{3}\s+(\d[\d.]*)\s+Made In\s+(\w+)\s+(\d{8,14})\b"
    )
    _invoice_no_re = re.compile(r"Invoice No:\s*(IP-\d+)", re.IGNORECASE)
    _invoice_date_re = re.compile(r"Invoice Date:\s*(\d{2})\.(\d{2})\.(\d{4})", re.IGNORECASE)
    _total_re = re.compile(r"Total\s*:\s*([\d.]+,\d+)\s*EUR", re.IGNORECASE)
    _payment_days_re = re.compile(r"\b(\d+)\s+DAYS\b", re.IGNORECASE)

    def __init__(self):
        self.extracted_transport_cost = 0.0
        self.invoice_number = ""
        self.invoice_date = ""
        self.payment_days = 30
        self.line_meta: list[dict] = []

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        pdf_total_amount = 0.0
        self.extracted_transport_cost = 0.0
        self.invoice_number = ""
        self.invoice_date = ""
        self.payment_days = 30
        self.line_meta = []

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            number = self._invoice_no_re.search(clean_line)
            if number:
                self.invoice_number = number.group(1)
            dated = self._invoice_date_re.search(clean_line)
            if dated:
                day, month, year = dated.groups()
                self.invoice_date = f"{year}-{month}-{day}"
            days = self._payment_days_re.search(clean_line)
            if days:
                self.payment_days = int(days.group(1))

            total = self._total_re.search(clean_line)
            if total:
                pdf_total_amount = self._amount(total.group(1))
                continue

            match = self._product_re.match(clean_line)
            if not match:
                continue
            code, description, qty_text, price_text, value_text, customs, origin, ean = match.groups()
            qty = int(qty_text.replace(".", ""))
            value = self._amount(value_text)
            if qty <= 0 or value <= 0:
                continue
            products_matrix.append(
                [
                    ean,
                    f"BN-{code}",
                    qty,
                    description.strip(),
                    self._amount(price_text),
                    0.0,
                    value,
                ]
            )
            self.line_meta.append({"origin": origin, "customs": customs})

        if pdf_total_amount == 0.0 and products_matrix:
            pdf_total_amount = round(sum(row[6] for row in products_matrix), 2)
        return products_matrix, pdf_total_amount

    @staticmethod
    def _amount(text: str) -> float:
        return float(text.replace(".", "").replace(",", "."))
