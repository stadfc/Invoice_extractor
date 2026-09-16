import re
from parsers.base import InvoiceParserStrategy

class ContactoInvoiceParser(InvoiceParserStrategy):
    keywords = ["contacto", "bander", "erkrath"]
    vendor_name = "Contacto"

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        pdf_total_amount = 0.0

        product_line_regex = re.compile(r"^(\d+/\d+)\s+(.+)")

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            if "0 0,00" in clean_line or "rechnungsbetrag" in clean_line.lower():
                parts = clean_line.split(" ")
                try:
                    raw_amount = parts[-1].replace(".", "").replace(",", ".")
                    pdf_total_amount = float(raw_amount)
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