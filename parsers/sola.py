import re
from parsers.base import InvoiceParserStrategy

class SolaInvoiceParser(InvoiceParserStrategy):
    keywords = ["slovakia", "ivanka", "sola switzerland"]
    vendor_name = "Sola Swiss"

    def __init__(self):
        self.extracted_transport_cost = 0.0

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        pdf_total_amount = 0.0
        self.extracted_transport_cost = 0.0

        # Qty may use a space as thousands separator, e.g. "1 200 pc."
        product_main_regex = re.compile(
            r"^(\d+)\s+([A-Z0-9]+)\s+(\d+(?:\s\d{3})*)\s+(?:pc\.\s+)?([0-9.,]+)\s+([0-9.,]+)$"
        )

        current_product = None
        block_terminators = ["subtotal", "grand total", "our general", "order confirmation", "kind regards", "page :"]

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            clean_line_lower = clean_line.lower()

            if "grand total eur" in clean_line_lower:
                parts = clean_line.split(" ")
                try:
                    raw_amount = "".join(parts[3:]).replace(".", "").replace(",", ".")
                    pdf_total_amount = float(raw_amount)
                except (ValueError, IndexError):
                    pass
                continue

            if current_product and any(term in clean_line_lower for term in block_terminators):
                products_matrix.append(self._finalize_product(current_product))
                current_product = None

            match = product_main_regex.match(clean_line)
            if match:
                if current_product:
                    products_matrix.append(self._finalize_product(current_product))
                    current_product = None

                pos = match.group(1)
                code = match.group(2)
                qty = int(match.group(3).replace(" ", ""))
                price = float(match.group(4).replace(".", "").replace(",", "."))
                value = float(match.group(5).replace(".", "").replace(",", "."))

                if code == "S001" or "freight" in clean_line_lower:
                    self.extracted_transport_cost = value
                    continue

                current_product = {
                    "ean": "0000000000000",
                    "product_code": f"SS-{code}",
                    "qty_shipped": qty,
                    "description_lines": [],
                    "price": price,
                    "discount": 0.0,
                    "value": value
                }
                continue

            if current_product:
                if "EAN:" in clean_line:
                    ean_match = re.search(r"EAN:\s*(\d+)", clean_line)
                    if ean_match:
                        current_product["ean"] = ean_match.group(1)
                        products_matrix.append(self._finalize_product(current_product))
                        current_product = None
                    continue

                ignore_terms = ["pos description", "qty unit price", "sola switzerland", "company id", "page :"]
                if any(term in clean_line_lower for term in ignore_terms):
                    continue

                current_product["description_lines"].append(clean_line)

        if current_product:
            products_matrix.append(self._finalize_product(current_product))

        if pdf_total_amount == 0.0:
            pdf_total_amount = round(sum(row[6] for row in products_matrix), 4)

        return products_matrix, pdf_total_amount

    def _finalize_product(self, prod_dict: dict) -> list:
        description = " ".join(prod_dict["description_lines"]).strip()
        return [
            prod_dict["ean"],
            prod_dict["product_code"],
            prod_dict["qty_shipped"],
            description,
            prod_dict["price"],
            prod_dict["discount"],
            prod_dict["value"]
        ]