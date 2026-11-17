import re

from parsers.base import InvoiceParserStrategy


class MesaInvoiceParser(InvoiceParserStrategy):
    keywords = ["mesacer ceramics", "mesa-ceramics"]
    vendor_name = "Mesa Ceramics"
    currency = "EUR"

    # Number Date Page, e.g. "13 1027/26001350 21/10/2026 1/3"
    _header_re = re.compile(
        r"^(\d+)\s+(\d+/\d+)\s+(\d{2})/(\d{2})/(\d{4})\s+(\d+)/(\d+)$"
    )
    # Item code, description, quantity, unit, tax, price, discount, amount.
    _product_re = re.compile(
        r"^(\d+)\s+(FF\d+)\s+(.+?)\s+(\d+)\s+UN\s+\d+\s+%\s+(\d+\.\d+)\s+\d+\.\d+%\s+([\d,]+\.\d+)$"
    )
    _total_re = re.compile(r"Total EUR\s+([\d,]+\.\d+)")

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
        seen_first_copy = False

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            header = self._header_re.match(clean_line)
            if header:
                page = int(header.group(6))
                # The PDF prints the same invoice three times. Keep the first copy.
                if page == 1 and seen_first_copy:
                    break
                if page == 1:
                    seen_first_copy = True
                    self.invoice_number = header.group(2)
                    day, month, year = header.group(3), header.group(4), header.group(5)
                    self.invoice_date = f"{year}-{month}-{day}"
                continue

            total = self._total_re.search(clean_line)
            if total:
                pdf_total_amount = float(total.group(1).replace(",", ""))
                continue

            match = self._product_re.match(clean_line)
            if not match:
                continue
            qty = int(match.group(4))
            value = float(match.group(6).replace(",", ""))
            if qty <= 0 or value <= 0:
                continue
            products_matrix.append(
                [
                    "0000000000000",
                    f"KJ-{match.group(2)}",
                    qty,
                    match.group(3).strip(),
                    float(match.group(5)),
                    0.0,
                    value,
                ]
            )

        if pdf_total_amount == 0.0 and products_matrix:
            pdf_total_amount = round(sum(row[6] for row in products_matrix), 2)
        return products_matrix, pdf_total_amount
