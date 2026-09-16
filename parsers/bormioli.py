import os
import re
import json
from parsers.base import InvoiceParserStrategy

class BormioliLuigiInvoiceParser(InvoiceParserStrategy):
    keywords = ["bormioli luigi", "parma", "viale europa"]
    vendor_name = "Bormioli Luigi"

    def __init__(self, config_path="bormioli_config.json"):
        self.config_path = config_path
        self.color_mappings = {}
        self.ean_color_exceptions = {}
        self.extracted_transport_cost = 0.0
        self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.color_mappings = config.get("color_mappings", {})
                    self.ean_color_exceptions = config.get("ean_color_exceptions", {})
            except Exception:
                self._set_internal_fallbacks()
        else:
            self._set_internal_fallbacks()

    def _set_internal_fallbacks(self):
        self.color_mappings = {"light blue": "LB", "lightblue": "LB", "cottoncandy": "CC", "cotton candy": "CC"}
        self.ean_color_exceptions = {"8004360091502": "LB", "8004360091519": "CC"}

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        shipping_cost = 0.0
        goods_net_total = 0.0
        self.extracted_transport_cost = 0.0

        product_main_regex = re.compile(r"^([A-Z0-9]{10,20})\s+(.+)")
        current_product = None
        block_terminators = ["epal", "goods net", "total", "page", "bank", "num ct", "declaration"]

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            clean_line_lower = clean_line.lower()
            clean_line_upper = clean_line.upper()

            if current_product and any(term in clean_line_lower for term in block_terminators):
                products_matrix.append(self._finalize_product(current_product))
                current_product = None

            if "epal" in clean_line_lower:
                parts = clean_line.split(" ")
                try:
                    val_idx = -2 if parts[-1] == "VE" else -1
                    raw_epal_val = parts[val_idx].replace(".", "").replace(",", ".")
                    shipping_cost += float(raw_epal_val)
                except (ValueError, IndexError):
                    pass
                continue

            if "goods net" in clean_line_lower and "total" in clean_line_lower:
                parts = clean_line.split(" ")
                try:
                    raw_total = parts[-1].replace(".", "").replace(",", ".")
                    goods_net_total = float(raw_total)
                except ValueError:
                    pass
                continue

            main_match = product_main_regex.match(clean_line)
            if main_match:
                if current_product:
                    products_matrix.append(self._finalize_product(current_product))

                raw_code = main_match.group(1)
                remainder = main_match.group(2).split(" ")
                formatted_code = self._format_item_code(raw_code)

                try:
                    unit_price, value = self._extract_unit_price_and_value(remainder)

                    description_parts = []
                    for part in remainder:
                        if part in ["100", "ZCO", "B"]:
                            break
                        description_parts.append(part)
                    description = " ".join(description_parts)

                    current_product = {
                        "ean": "0000000000000",
                        "base_code": formatted_code,
                        "color_suffix": "",
                        "qty_shipped": 0,
                        "description": description,
                        "price": round(unit_price, 4),
                        "discount": 0.0,
                        "value": round(value, 4)
                    }
                except (ValueError, IndexError):
                    current_product = None
                continue

            if current_product:
                if "EAN:" in clean_line or "Pce:" in clean_line:
                    pce_match = re.search(r"Pce:\s*([0-9.,]+)", clean_line)
                    if pce_match:
                        try:
                            raw_pce = pce_match.group(1).split(",")[0]
                            current_product["qty_shipped"] = int(raw_pce.replace(".", ""))
                        except ValueError:
                            pass

                    ean_match = re.search(r"EAN:\s*([0-9]+)", clean_line)
                    if ean_match:
                        ean_str = ean_match.group(1)
                        current_product["ean"] = ean_str
                        if ean_str in self.ean_color_exceptions:
                            current_product["color_suffix"] = self.ean_color_exceptions[ean_str]

                if not current_product["color_suffix"]:
                    for color_name, suffix in self.color_mappings.items():
                        if color_name.upper() in clean_line_upper:
                            current_product["color_suffix"] = suffix
                            break

        if current_product:
            products_matrix.append(self._finalize_product(current_product))

        if goods_net_total == 0.0:
            goods_net_total = sum(row[6] for row in products_matrix)

        self.extracted_transport_cost = round(shipping_cost, 4)
        pdf_total_amount = round(goods_net_total + shipping_cost, 4)
        return products_matrix, pdf_total_amount

    @staticmethod
    def _format_item_code(raw_code: str) -> str:
        """All-digit supplier codes stay whole; lettered codes use BL-X.XXXXX."""
        if re.fullmatch(r"\d+", raw_code):
            return f"BL-{raw_code}"
        return f"BL-{raw_code[0]}.{raw_code[1:6]}"

    @staticmethod
    def _extract_unit_price_and_value(remainder: list[str]) -> tuple[float, float]:
        skipped = {"VE", "EUR", "X"}
        numbers: list[float] = []
        for token in remainder:
            if token.upper() in skipped:
                continue
            try:
                numbers.append(float(token.replace(".", "").replace(",", ".")))
            except ValueError:
                continue
        if len(numbers) < 2:
            raise ValueError("missing price/value")
        unit_price = numbers[-2] / 100.0
        value = numbers[-1]
        return unit_price, value

    def _finalize_product(self, prod_dict: dict) -> list:
        final_code = prod_dict["base_code"]
        if prod_dict["color_suffix"]:
            final_code = f"{final_code}-{prod_dict['color_suffix']}"

        qty = prod_dict["qty_shipped"]
        val = prod_dict["value"]
        price_per_piece = round(val / qty, 4) if qty > 0 else 0.0

        return [
            prod_dict["ean"],
            final_code,
            qty,
            prod_dict["description"],
            price_per_piece,
            prod_dict["discount"],
            val
        ]