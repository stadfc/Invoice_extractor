import re
from parsers.base import InvoiceParserStrategy

class PintinoxInvoiceParser(InvoiceParserStrategy):
    keywords = ["pinti inox", "sarezzo", "pintinox"]
    vendor_name = "Pintinox"

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        pdf_total_amount = 0.0

        product_main_regex = re.compile(r"^([A-Z0-9]{8})\s+(.+)\s+(NR)\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)N\d+")

        current_product = None

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            clean_line_lower = clean_line.lower()

            if "invoice total" in clean_line_lower:
                parts = clean_line.split(" ")
                try:
                    pdf_total_amount = float(parts[-1].replace(".", "").replace(",", "."))
                except (ValueError, IndexError):
                    pass
                continue

            main_match = product_main_regex.match(clean_line)
            if main_match:
                if current_product:
                    products_matrix.append(self._finalize_product(current_product))

                raw_code = main_match.group(1)
                description = main_match.group(2).strip()
                qty = int(float(main_match.group(4).replace(".", "").replace(",", ".")))
                price = float(main_match.group(5).replace(".", "").replace(",", "."))
                value = float(main_match.group(6).replace(".", "").replace(",", "."))

                if price > value and qty > 0:
                    price = price / 1000.0

                current_product = {
                    "ean": "0000000000000",
                    "product_code": f"PI-{raw_code}",
                    "qty_shipped": qty,
                    "description": description,
                    "price": price,
                    "discount": 0.0,
                    "value": value
                }
                continue

            if current_product:
                ean_match = re.search(r"\((\d{13})\)", clean_line)
                if ean_match:
                    current_product["ean"] = ean_match.group(1)
                    products_matrix.append(self._finalize_product(current_product))
                    current_product = None

        if current_product:
            products_matrix.append(self._finalize_product(current_product))

        if pdf_total_amount == 0.0:
            pdf_total_amount = round(sum(row[6] for row in products_matrix), 4)

        return products_matrix, pdf_total_amount

    def _finalize_product(self, prod_dict: dict) -> list:
        qty = prod_dict["qty_shipped"]
        val = prod_dict["value"]
        price_per_piece = round(val / qty, 4) if qty > 0 else 0.0

        return [
            prod_dict["ean"],
            prod_dict["product_code"],
            qty,
            prod_dict["description"],
            price_per_piece,
            prod_dict["discount"],
            val
        ]