import re
from parsers.base import InvoiceParserStrategy


class LeoneInvoiceParser(InvoiceParserStrategy):
    keywords = ["leone", "lugo"]
    vendor_name = "Leone"

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        pdf_total_amount = 0.0

        # Regex obsługujący oba formaty pozycji Leone:
        # Kod | Opis (opcjonalny) | Jednostka | Ilość | [opcjonalny Kod EAN/Lotto] | Cena | Rabat (% lub %+) | Wartość | IVA
        product_regex = re.compile(
            r"^([A-Z0-9.]+)\s+(?:(.*?)\s+)?(CONF|PZ)\s+([0-9.,]+)\s+(?:\d+\s+)?([0-9.,]+)\s+([\d+]+)\s+([0-9.,]+)\s*(?:NI\d+|IVA\d+)?"
        )

        current_product = None

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            # 1. Odczyt ostatecznej kwoty faktury z podsumowania (np. Totale fattura, Totale da pagare, Imponibile + Imposta)
            if any(term in clean_line for term in ["Totale fattura", "Totale da pagare", "Imponibile + Imposta"]):
                parts = clean_line.split()
                for part in reversed(parts):
                    # Radzimy sobie z zapisem 1.190,92 oraz 1.190.92
                    cleaned_val = part.replace(".", "").replace(",", ".")
                    try:
                        val = float(cleaned_val)
                        if val > 0:
                            pdf_total_amount = val
                            break
                    except ValueError:
                        pass

            # Pomiń nagłówki tabeli i adnotacje stopki
            if clean_line.startswith("Articolo") or clean_line.startswith("NON SI ACCETTANO"):
                if current_product:
                    products_matrix.append(self._finalize_product(current_product))
                    current_product = None
                continue

            # 2. Dopasowanie głównego wiersza produktu
            match = product_regex.match(clean_line)
            if match:
                if current_product:
                    products_matrix.append(self._finalize_product(current_product))

                raw_code = match.group(1)
                raw_desc = match.group(2).strip() if match.group(2) else ""
                qty = int(float(match.group(4).replace(".", "").replace(",", ".")))
                price = float(match.group(5).replace(".", "").replace(",", "."))
                discount_str = match.group(6)
                value = float(match.group(7).replace(".", "").replace(",", "."))

                # Obsługa rabatu: pojedynczego (np. 53) lub składanego (np. 53+10)
                if "+" in discount_str:
                    try:
                        d1, d2 = map(float, discount_str.split("+"))
                        combined_discount = (1.0 - (1.0 - d1 / 100.0) * (1.0 - d2 / 100.0)) * 100.0
                        combined_discount = round(combined_discount, 2)
                    except Exception:
                        combined_discount = 0.0
                else:
                    try:
                        combined_discount = float(discount_str)
                    except ValueError:
                        combined_discount = 0.0

                current_product = {
                    "ean": "0000000000000",
                    "product_code": f"LE-{raw_code}",
                    "qty_shipped": qty,
                    "description": raw_desc,
                    "price": price,
                    "discount": combined_discount,
                    "value": value
                }
                continue

            # 3. Zbieranie dodatkowych linii opisu (np. Lotto: ..., dopisy)
            if current_product:
                bad_terms = ["Products Leone", "Cosmetics products", "Tax Description", "Fees €", "Amount €",
                             "Deposit €", "Forwarder", "Transport", "Number of packages", "... continua",
                             "Customer:", "IVA", "Descrizione", "Imponibile", "Totale", "Contributo"]

                if any(term in clean_line for term in bad_terms):
                    products_matrix.append(self._finalize_product(current_product))
                    current_product = None
                    continue

                if current_product["description"]:
                    current_product["description"] += f" {clean_line}"
                else:
                    current_product["description"] = clean_line

        if current_product:
            products_matrix.append(self._finalize_product(current_product))

        # Ustalamy końcową sumę faktury
        if pdf_total_amount == 0.0:
            pdf_total_amount = round(sum(row[6] for row in products_matrix), 4)
        else:
            pdf_total_amount = round(pdf_total_amount, 4)

        return products_matrix, pdf_total_amount

    def _finalize_product(self, prod_dict: dict) -> list:
        return [
            prod_dict["ean"],
            prod_dict["product_code"],
            prod_dict["qty_shipped"],
            prod_dict["description"],
            prod_dict["price"],
            prod_dict["discount"],
            prod_dict["value"]
        ]