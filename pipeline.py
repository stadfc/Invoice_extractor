"""Shared invoice processing steps used by the GUI and batch export.

Mirrors the manual clicks: drop zero rows, then format for ERP import.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pdfplumber

from parsers.factory import InvoiceParserFactory

SOURCE_COLUMNS = [
    "EAN",
    "Product_code",
    "Qty_shipped",
    "Description",
    "Price",
    "Discount",
    "Value",
]
IMPORT_COLUMNS = ["Kod", "Ilość", "Cena jednostkowa"]
VENDORS_REQUIRING_TRANSPORT = frozenset({"Leone", "Sola Swiss"})
PRICE_SCALE = 10000  # 0.0001 currency steps
CURRENCY_SYMBOLS = {
    "EUR": "€",
    "GBP": "£",
    "USD": "$",
    "PLN": "zł",
}


def format_money(amount: float, currency: str = "EUR") -> str:
    code = (currency or "EUR").upper()
    symbol = CURRENCY_SYMBOLS.get(code, code)
    return f"{amount:.2f} {symbol}"


def _price_to_units(price: float) -> int:
    return int(round(float(price) * PRICE_SCALE))


def _sumproduct_from_units(rows: list[dict]) -> int:
    return sum(int(row["_price_units"]) * int(row["Ilość"]) for row in rows)


def _apply_qty_knapsack(import_rows: list[dict], remaining: int) -> bool:
    """Change unit prices so sum(qty * 0.0001) equals remaining (signed)."""
    if remaining == 0:
        return True
    direction = 1 if remaining > 0 else -1
    amount = abs(remaining)
    if amount > 500_000:
        return False
    qtys = [int(row["Ilość"]) for row in import_rows]
    parent = [-1] * (amount + 1)
    used_row = [-1] * (amount + 1)
    parent[0] = 0
    for i, qty in enumerate(qtys):
        if qty <= 0 or qty > amount:
            continue
        if direction < 0 and int(import_rows[i]["_price_units"]) <= 1:
            continue
        for total in range(qty, amount + 1):
            if parent[total] != -1 or parent[total - qty] == -1:
                continue
            parent[total] = total - qty
            used_row[total] = i
        if parent[amount] != -1:
            break
    if parent[amount] == -1:
        return False

    total = amount
    while total > 0:
        idx = used_row[total]
        next_units = int(import_rows[idx]["_price_units"]) + direction
        if next_units <= 0:
            return False
        import_rows[idx]["_price_units"] = next_units
        total = parent[total]
    return True


def align_unit_prices_to_invoice_total(
    import_rows: list[dict], target_total: float
) -> tuple[float, bool]:
    """Nudge 4-decimal unit prices so qty * price sums to the invoice total.

    Excel SUMPRODUCT uses the raw product, not per-line rounding to 2 decimals.
    Work in integer 0.0001 units so binary floats cannot drift.
    """
    target_units = int(round(float(target_total) * PRICE_SCALE))
    for row in import_rows:
        row["_price_units"] = _price_to_units(row["Cena jednostkowa"])

    remaining = target_units - _sumproduct_from_units(import_rows)
    if remaining != 0:
        if not _apply_qty_knapsack(import_rows, remaining):
            for _ in range(20000):
                remaining = target_units - _sumproduct_from_units(import_rows)
                if remaining == 0:
                    break
                direction = 1 if remaining > 0 else -1
                need = abs(remaining)
                fitting: list[tuple[int, int]] = []
                for idx, row in enumerate(import_rows):
                    qty = int(row["Ilość"])
                    if qty <= 0 or qty > need:
                        continue
                    next_units = int(row["_price_units"]) + direction
                    if next_units <= 0:
                        continue
                    fitting.append((idx, qty))
                if not fitting:
                    break
                idx, _qty = max(fitting, key=lambda item: item[1])
                import_rows[idx]["_price_units"] += direction

    exact = _sumproduct_from_units(import_rows) == target_units
    for row in import_rows:
        row["Cena jednostkowa"] = round(row["_price_units"] / PRICE_SCALE, 4)
        del row["_price_units"]

    raw_sum = sum(row["Cena jednostkowa"] * int(row["Ilość"]) for row in import_rows)
    return round(raw_sum, 4), exact


@dataclass(frozen=True)
class ParseResult:
    vendor: str
    pdf_total_amount: float
    transport_cost: float
    transport_is_external: bool
    rows: pd.DataFrame
    invoice_number: str = ""
    currency: str = "EUR"


@dataclass(frozen=True)
class ImportFormatResult:
    df: pd.DataFrame
    total_net_goods: float
    header_discount: float
    transport_cost: float
    target_grand_total: float
    simulated_sum: float
    matched: bool


def extract_pdf_text(pdf_path: Path) -> tuple[str, list[str]]:
    full_pdf_text = ""
    all_lines: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_pdf_text += page_text + "\n"
                all_lines.extend(page_text.split("\n"))
    return full_pdf_text, all_lines


def parse_invoice(
    pdf_path: Path,
    *,
    transport_cost: float = 0.0,
    factory: InvoiceParserFactory | None = None,
) -> ParseResult:
    full_pdf_text, all_lines = extract_pdf_text(pdf_path)
    if not full_pdf_text.strip():
        raise ValueError("No extractable text in PDF")

    factory = factory or InvoiceParserFactory()
    parser = factory.get_parser_for_text(full_pdf_text)
    if parser is None:
        raise ValueError("Unknown vendor / invoice format")

    products_matrix, pdf_total_amount = parser.parse(all_lines)
    if not products_matrix:
        raise ValueError(f"No line items extracted for {parser.vendor_name}")

    extracted_transport = float(getattr(parser, "extracted_transport_cost", 0.0) or 0.0)
    if extracted_transport > 0.0:
        used_transport = extracted_transport
        transport_is_external = False
    else:
        used_transport = float(transport_cost)
        transport_is_external = used_transport > 0.0

    df = pd.DataFrame(products_matrix, columns=SOURCE_COLUMNS)
    return ParseResult(
        vendor=parser.vendor_name,
        pdf_total_amount=float(pdf_total_amount or 0.0),
        transport_cost=used_transport,
        transport_is_external=transport_is_external,
        rows=df,
        currency=str(getattr(parser, "currency", "EUR") or "EUR"),
    )


def parse_invoices(
    pdf_path: Path,
    *,
    transport_cost: float = 0.0,
    factory: InvoiceParserFactory | None = None,
) -> list[ParseResult]:
    """Parse a PDF into one or more invoices (Churchill collated files)."""
    full_pdf_text, all_lines = extract_pdf_text(pdf_path)
    if not full_pdf_text.strip():
        raise ValueError("No extractable text in PDF")

    factory = factory or InvoiceParserFactory()
    parser = factory.get_parser_for_text(full_pdf_text)
    if parser is None:
        raise ValueError("Unknown vendor / invoice format")

    if hasattr(parser, "parse_documents"):
        documents = parser.parse_documents(all_lines)
        results: list[ParseResult] = []
        for doc in documents:
            products = getattr(doc, "products", None)
            if not products:
                continue
            freight = float(getattr(doc, "freight", 0.0) or 0.0)
            if freight > 0.0:
                used_transport = freight
                transport_is_external = False
            else:
                used_transport = float(transport_cost)
                transport_is_external = used_transport > 0.0
            results.append(
                ParseResult(
                    vendor=parser.vendor_name,
                    pdf_total_amount=float(getattr(doc, "invoice_total", 0.0) or 0.0),
                    transport_cost=used_transport,
                    transport_is_external=transport_is_external,
                    rows=pd.DataFrame(products, columns=SOURCE_COLUMNS),
                    invoice_number=str(getattr(doc, "invoice_number", "") or ""),
                    currency=str(
                        getattr(doc, "currency", None)
                        or getattr(parser, "currency", "EUR")
                        or "EUR"
                    ),
                )
            )
        if not results:
            raise ValueError(f"No line items extracted for {parser.vendor_name}")
        return results

    return [parse_invoice(pdf_path, transport_cost=transport_cost, factory=factory)]


def drop_zero_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    if "Ilość" in df.columns:
        mask = (df["Ilość"] > 0) & (df["Cena jednostkowa"] > 0)
    else:
        mask = (df["Qty_shipped"] > 0) & (df["Value"] > 0)
    return df.loc[mask].reset_index(drop=True)


def format_for_import(
    df: pd.DataFrame,
    pdf_total_amount: float,
    transport_cost: float = 0.0,
) -> ImportFormatResult:
    if df.empty:
        raise ValueError("No rows to format")

    working = drop_zero_rows(df)
    total_net_goods = float(working["Value"].sum())
    if total_net_goods <= 0:
        raise ValueError("Sum of product values is 0")

    header_discount = 0.0
    diff_pdf_vs_goods = round(pdf_total_amount - total_net_goods, 2)
    if diff_pdf_vs_goods < -0.10:
        header_discount = abs(diff_pdf_vs_goods)

    target_grand_total = round(total_net_goods - header_discount + transport_cost, 2)
    net_adjustment = transport_cost - header_discount
    adjustment_coefficient = net_adjustment / total_net_goods

    import_rows: list[dict] = []
    for _, row in working.iterrows():
        qty = int(row["Qty_shipped"])
        if qty <= 0:
            continue
        allocated_value = row["Value"] * (1.0 + adjustment_coefficient)
        unit_price = round(allocated_value / qty, 4)
        import_rows.append(
            {
                "Kod": row["Product_code"],
                "Ilość": qty,
                "Cena jednostkowa": unit_price,
            }
        )

    if not import_rows:
        raise ValueError("No positive-qty rows after cleanup")

    raw_sum, exact = align_unit_prices_to_invoice_total(import_rows, target_grand_total)
    simulated_sum = round(raw_sum, 2)
    result_df = pd.DataFrame(import_rows, columns=IMPORT_COLUMNS)
    result_df["Cena jednostkowa"] = result_df["Cena jednostkowa"].round(4)
    return ImportFormatResult(
        df=result_df,
        total_net_goods=total_net_goods,
        header_discount=header_discount,
        transport_cost=transport_cost,
        target_grand_total=target_grand_total,
        simulated_sum=simulated_sum,
        matched=exact and simulated_sum == target_grand_total,
    )


def needs_manual_transport(vendor: str, transport_cost: float) -> bool:
    return vendor in VENDORS_REQUIRING_TRANSPORT and transport_cost <= 0.0
