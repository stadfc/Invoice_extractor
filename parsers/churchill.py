from __future__ import annotations

import re
from dataclasses import dataclass, field

from parsers.base import InvoiceParserStrategy


@dataclass
class ChurchillDocument:
    invoice_number: str
    products: list[list] = field(default_factory=list)
    invoice_total: float = 0.0
    freight: float = 0.0
    currency: str = "GBP"


class ChurchillInvoiceParser(InvoiceParserStrategy):
    keywords = ["churchill china", "tunstall", "stoke-on-trent", "marlborough"]
    vendor_name = "Churchill"
    currency = "GBP"

    DESCRIPTION_START = frozenset({"STONECAST", "WHITE", "STUDIO", "FREIGHT"})
    INVOICE_NO_RE = re.compile(r"\b(CD\d{10})\b")

    def __init__(self):
        self.extracted_transport_cost = 0.0

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        documents = self.parse_documents(page_text_list)
        if not documents:
            return [], 0.0
        if len(documents) == 1:
            self.extracted_transport_cost = documents[0].freight
        else:
            self.extracted_transport_cost = 0.0
        rows: list[list] = []
        total = 0.0
        for doc in documents:
            rows.extend(doc.products)
            total += doc.invoice_total
        return rows, round(total, 4)

    def parse_documents(self, page_text_list: list[str]) -> list[ChurchillDocument]:
        self.extracted_transport_cost = 0.0
        documents: dict[str, ChurchillDocument] = {}
        current_no = ""
        in_packing = False
        look_for_total = False

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue
            upper = clean_line.upper()

            if "INVOICE PACKING SUMMARY" in upper:
                in_packing = True
                look_for_total = False
                continue
            if "INVOICE FOR PAYMENT PURPOSES" in upper:
                in_packing = False
                look_for_total = False
                continue
            if in_packing:
                continue

            invoice_match = self.INVOICE_NO_RE.search(clean_line)
            if invoice_match:
                current_no = invoice_match.group(1)
                documents.setdefault(current_no, ChurchillDocument(invoice_number=current_no))

            if current_no:
                currency_match = re.search(r"\b(GBP|EUR|USD|PLN)\b", clean_line)
                if currency_match and "SWIFT" not in clean_line.upper() and "IBAN" not in clean_line.upper():
                    documents[current_no].currency = currency_match.group(1)

            if look_for_total and current_no:
                total = self._parse_gbp_amount(clean_line)
                if total is not None:
                    documents[current_no].invoice_total = total
                    look_for_total = False
                continue

            if "INVOICE TOTAL" in upper:
                look_for_total = True
                continue

            if current_no and upper.startswith("FREIGHT"):
                freight = self._parse_freight(clean_line)
                if freight is not None:
                    documents[current_no].freight = freight
                continue

            product = self._parse_product_line(clean_line)
            if product and current_no:
                documents[current_no].products.append(product)

        result = list(documents.values())
        for doc in result:
            goods = round(sum(row[6] for row in doc.products), 2)
            if doc.invoice_total <= 0:
                doc.invoice_total = round(goods + doc.freight, 2)
        return result

    @staticmethod
    def format_item_code(raw_code: str) -> str:
        compact = re.sub(r"\s+", "", raw_code).upper()
        return f"CH-{compact}"

    def _parse_product_line(self, clean_line: str) -> list | None:
        parts = clean_line.split()
        if len(parts) < 5:
            return None
        hs_code = parts[-4]
        if not (hs_code.isdigit() and len(hs_code) == 10):
            return None
        try:
            qty = int(parts[-3].replace(" ", ""))
            price = float(parts[-2])
            value = float(parts[-1])
        except ValueError:
            return None

        left = parts[:-4]
        code_parts: list[str] = []
        desc_parts: list[str] = []
        for index, token in enumerate(left):
            if token.upper() in self.DESCRIPTION_START:
                desc_parts = left[index:]
                break
            code_parts.append(token)
        if not code_parts:
            return None

        description = " ".join(desc_parts).strip()
        return [
            "0000000000000",
            self.format_item_code(" ".join(code_parts)),
            qty,
            description,
            round(price, 4),
            0.0,
            round(value, 4),
        ]

    @staticmethod
    def _parse_freight(clean_line: str) -> float | None:
        parts = clean_line.split()
        for token in reversed(parts):
            try:
                return float(token)
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_gbp_amount(clean_line: str) -> float | None:
        parts = clean_line.replace("GBP", " ").split()
        if not parts:
            return None
        try:
            return float(parts[-1])
        except ValueError:
            return None
