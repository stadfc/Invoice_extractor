import re
from parsers.base import InvoiceParserStrategy

class ContactoInvoiceParser(InvoiceParserStrategy):
    keywords = ["contacto", "bander", "erkrath"]
    vendor_name = "Contacto"

    # Warenwert, Versandkostenanteil, Zwischensumme, VAT rate, VAT, Rechnungsbetrag.
    _totals_re = re.compile(
        r"^([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+\d+\s+[\d.]+,\d{2}\s+([\d.]+,\d{2})$"
    )
    # Same row when the carriage column is left blank because freight is zero.
    _totals_without_carriage_re = re.compile(
        r"^([\d.]+,\d{2})\s+([\d.]+,\d{2})\s+\d+\s+[\d.]+,\d{2}\s+([\d.]+,\d{2})$"
    )
    _invoice_no_re = re.compile(r"\bINVOICE\s+(\d+-\d+)\b", re.IGNORECASE)
    _date_re = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

    def __init__(self):
        self.extracted_transport_cost = 0.0
        self.invoice_number = ""
        self.invoice_date = ""

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        pdf_total_amount = 0.0
        self.extracted_transport_cost = 0.0
        self.invoice_number = ""
        self.invoice_date = ""

        product_line_regex = re.compile(r"^(\d+/\d+)\s+(.+)")

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            number = self._invoice_no_re.search(clean_line)
            if number:
                self.invoice_number = number.group(1)
            if not self.invoice_date:
                dated = self._date_re.search(clean_line)
                if dated:
                    year, month, day = dated.groups()
                    self.invoice_date = f"{year}-{month}-{day}"

            totals = self._totals_re.match(clean_line)
            if totals:
                self.extracted_transport_cost = self._amount(totals.group(2))
                pdf_total_amount = self._amount(totals.group(4))
                continue
            totals = self._totals_without_carriage_re.match(clean_line)
            if totals:
                goods_amount = self._amount(totals.group(1))
                net_amount = self._amount(totals.group(2))
                self.extracted_transport_cost = round(max(net_amount - goods_amount, 0.0), 2)
                pdf_total_amount = self._amount(totals.group(3))
                continue

            if "rechnungsbetrag" in clean_line.lower():
                parts = clean_line.split(" ")
                try:
                    pdf_total_amount = self._amount(parts[-1])
                except ValueError:
                    pass
                continue

            match = product_line_regex.match(clean_line)
            if match:
                product_code = match.group(1)
                remainder = match.group(2).split(" ")

                if len(remainder) < 4:
                    continue

                try:
                    row_data = []
                    row_data.append("0000000000000")  # EAN
                    row_data.append(f"CO-{product_code}")  # Kod produktu z prefiksem

                    if len(remainder) >= 4 and (remainder[-3] == "0" or remainder[-3] == "0,00"):
                        qty_shipped = 0
                        price = float(remainder[-2].replace(".", "").replace(",", "."))
                        discount = float(remainder[-1].replace(".", "").replace(",", "."))
                        value = 0.0
                        description = " ".join(remainder[:-4])
                    else:
                        qty_shipped = int(remainder[-4])
                        price = float(remainder[-3].replace(".", "").replace(",", "."))
                        discount = float(remainder[-2].replace(".", "").replace(",", "."))
                        value = float(remainder[-1].replace(".", "").replace(",", "."))
                        description = " ".join(remainder[:-5])

                    row_data.append(qty_shipped)
                    row_data.append(description)
                    row_data.append(price)
                    row_data.append(discount)
                    row_data.append(value)

                    products_matrix.append(row_data)
                except (ValueError, IndexError):
                    continue

        return products_matrix, pdf_total_amount

    @staticmethod
    def _amount(text: str) -> float:
        return float(text.replace(".", "").replace(",", "."))