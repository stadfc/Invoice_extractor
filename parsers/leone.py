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
        self.invoice_number = ""
        self.invoice_date = ""
        invoice_no = re.compile(r"\b(\d{6}/\d{2}[A-Z])\s+(\d{2})/(\d{2})/(\d{4})\b")
        # pdfplumber often puts the summary labels and the amounts on two lines:
        # "Totale fattura" then "0,00 1.091,41 0,00 1.091,41"
        pending_total = False

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            if not self.invoice_number:
                number_match = invoice_no.search(clean_line)
                if number_match:
                    self.invoice_number = number_match.group(1)
                    day, month, year = number_match.group(2), number_match.group(3), number_match.group(4)
                    self.invoice_date = f"{year}-{month}-{day}"

            if pending_total:
                pending_total = False
                total = self._last_positive_amount(clean_line)
                if total is not None:
                    pdf_total_amount = total
                    continue

            # 1. Invoice total. The payable amount wins when both labels exist,
            # so a later "Totale da pagare" replaces "Totale fattura".
            if any(term in clean_line for term in ["Totale fattura", "Totale da pagare", "Imponibile + Imposta"]):
                total = self._last_positive_amount(clean_line)
                if total is not None:
                    pdf_total_amount = total
                else:
                    pending_total = True

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

    @staticmethod
    def _last_positive_amount(clean_line: str) -> float | None:
        """Last European amount on a line (1.091,41 or 1.190.92)."""
        found = None
        for part in clean_line.replace("€", " ").split():
            if not any(ch.isdigit() for ch in part):
                continue
            cleaned = part.replace(".", "").replace(",", ".")
            try:
                val = float(cleaned)
            except ValueError:
                continue
            if val > 0:
                found = val
        return found

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