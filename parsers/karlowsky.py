from __future__ import annotations

import re
from dataclasses import dataclass, field

from parsers.base import InvoiceParserStrategy


SIZE_RE = re.compile(r"^(?:[2-5]XL|XXXL|XXL|XL|XS|S|M|L)$", re.IGNORECASE)
SKU_RE = re.compile(r"^([A-Z]{1,8})\s+(\d+)/(\d+)\s+(.+)$")
POS_HEADER_RE = re.compile(r"^\d+\s+[A-Z]{1,8}\s+\d+\s+")
INVOICE_NO_RE = re.compile(r"Invoice no\.:\s*(\d+)", re.IGNORECASE)


@dataclass
class KarlowskyDocument:
    invoice_number: str
    products: list[list] = field(default_factory=list)
    invoice_total: float = 0.0
    freight: float = 0.0
    currency: str = "EUR"


class KarlowskyInvoiceParser(InvoiceParserStrategy):
    keywords = ["karlowsky.de", "karlowsky"]
    vendor_name = "Karlowsky"
    currency = "EUR"

    def __init__(self):
        self.extracted_transport_cost = 0.0
        self.invoice_number = ""

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        documents = self.parse_documents(page_text_list)
        if not documents:
            return [], 0.0
        self.extracted_transport_cost = documents[0].freight
        self.invoice_number = documents[0].invoice_number
        rows: list[list] = []
        total = 0.0
        for doc in documents:
            rows.extend(doc.products)
            total += doc.invoice_total
        return rows, round(total, 4)

    def parse_documents(self, page_text_list: list[str]) -> list[KarlowskyDocument]:
        self.extracted_transport_cost = 0.0
        self.invoice_number = ""
        doc = KarlowskyDocument(invoice_number="")
        pending: dict | None = None

        for line in page_text_list:
            clean_line = line.strip()
            if not clean_line:
                continue

            invoice_match = INVOICE_NO_RE.search(clean_line)
            if invoice_match:
                doc.invoice_number = invoice_match.group(1)
                self.invoice_number = doc.invoice_number

            lower = clean_line.lower()
            if "postage:" in lower:
                postage = self._last_eu_number(clean_line)
                if postage is not None:
                    doc.freight = postage
                    self.extracted_transport_cost = postage
                continue

            if re.match(r"^amount:\s*", lower) and "total amount" not in lower:
                amount = self._last_eu_number(clean_line)
                if amount is not None:
                    doc.invoice_total = amount
                continue

            if pending is not None:
                qtys = self._parse_qty_line(clean_line)
                if qtys is not None:
                    doc.products.extend(self._rows_from_pending(pending, qtys))
                    pending = None
                    continue
                doc.products.extend(self._rows_from_pending(pending, None))
                pending = None

            sku = self._parse_sku_line(clean_line)
            if sku is not None:
                pending = sku
                continue

        if pending is not None:
            doc.products.extend(self._rows_from_pending(pending, None))

        if doc.invoice_total <= 0 and doc.products:
            goods = round(sum(row[6] for row in doc.products), 2)
            doc.invoice_total = round(goods + doc.freight, 2)

        if not doc.products:
            return []
        return [doc]

    @staticmethod
    def format_item_code(article: str, color: str, size: str) -> str:
        article_compact = re.sub(r"\s+", "", article).upper()
        color_digits = re.sub(r"\D", "", color)
        if color_digits:
            color_part = str(int(color_digits))
        else:
            color_part = color.lstrip("0") or color
        return f"KAR-{article_compact}/{color_part}/{size.upper()}"

    def _parse_sku_line(self, clean_line: str) -> dict | None:
        tokens = clean_line.split()
        if POS_HEADER_RE.match(clean_line) and len(tokens) > 1 and "/" not in tokens[1]:
            return None
        match = SKU_RE.match(clean_line)
        if not match:
            return None
        article = f"{match.group(1)} {match.group(2)}"
        color = match.group(3)
        rest_tokens = match.group(4).split()
        if len(rest_tokens) < 4:
            return None
        try:
            line_total = self._parse_eu_number(rest_tokens[-1])
            unit_price = self._parse_eu_number(rest_tokens[-2])
            total_qty = int(rest_tokens[-3].replace(" ", ""))
        except ValueError:
            return None

        middle = rest_tokens[:-3]
        size_tokens: list[str] = []
        while middle and SIZE_RE.match(middle[-1]):
            size_tokens.insert(0, middle.pop().upper())
        if not size_tokens:
            return None
        color_name = " ".join(middle).strip()
        return {
            "article": article,
            "color": color,
            "color_name": color_name,
            "sizes": size_tokens,
            "total_qty": total_qty,
            "unit_price": unit_price,
            "line_total": line_total,
        }

    def _rows_from_pending(self, pending: dict, qtys: list[int] | None) -> list[list]:
        sizes: list[str] = pending["sizes"]
        if qtys is None or len(qtys) != len(sizes):
            if len(sizes) == 1:
                qtys = [pending["total_qty"]]
            else:
                return []
        unit_price = float(pending["unit_price"])
        rows = []
        for size, qty in zip(sizes, qtys):
            if qty <= 0:
                continue
            value = round(qty * unit_price, 4)
            description = " ".join(
                part for part in (pending["article"], pending["color_name"], size) if part
            )
            rows.append(
                [
                    "0000000000000",
                    self.format_item_code(pending["article"], pending["color"], size),
                    qty,
                    description,
                    round(unit_price, 4),
                    0.0,
                    value,
                ]
            )
        return rows

    @staticmethod
    def _parse_qty_line(clean_line: str) -> list[int] | None:
        if not re.fullmatch(r"\d+(?:\s+\d+)*", clean_line):
            return None
        return [int(token) for token in clean_line.split()]

    @staticmethod
    def _parse_eu_number(token: str) -> float:
        return float(token.replace(".", "").replace(",", "."))

    def _last_eu_number(self, clean_line: str) -> float | None:
        for token in reversed(clean_line.replace(":", " ").split()):
            try:
                return self._parse_eu_number(token)
            except ValueError:
                continue
        return None
