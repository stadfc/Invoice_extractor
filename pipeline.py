"""Shared invoice processing steps used by the GUI and batch export.

Mirrors the manual clicks: drop zero rows, then format for ERP import.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
VENDORS_REQUIRING_TRANSPORT = frozenset({"Leone", "Sola Swiss", "Mesa Ceramics", "Bonna"})
# Country-wide anti-dumping duty on Chinese porcelain (CN 6911).
# Commission Implementing Regulation (EU) 2026/274, in force from 7 February 2026.
CHINA_PORCELAIN_ANTIDUMPING_RATE = 0.79
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


def _apply_qty_knapsack(import_rows: list[dict], remaining: int, *, allow_negative: bool = False) -> bool:
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
        if direction < 0 and int(import_rows[i]["_price_units"]) <= 1 and not allow_negative:
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
        if next_units <= 0 and not allow_negative:
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
    allow_negative = target_units < 0 or any(int(row["_price_units"]) < 0 for row in import_rows)

    remaining = target_units - _sumproduct_from_units(import_rows)
    if remaining != 0:
        if not _apply_qty_knapsack(import_rows, remaining, allow_negative=allow_negative):
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
                    if next_units <= 0 and not allow_negative:
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
    invoice_date: str = ""
    currency: str = "EUR"
    payment_days: int = 30
    # This invoice's share of freight from the whole pack. None means the
    # warehouse value follows the purchase document.
    warehouse_transport: float | None = None


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

    return ParseResult(
        vendor=parser.vendor_name,
        pdf_total_amount=float(pdf_total_amount or 0.0),
        transport_cost=used_transport,
        transport_is_external=transport_is_external,
        rows=_invoice_frame(products_matrix, parser),
        invoice_number=str(getattr(parser, "invoice_number", "") or ""),
        invoice_date=str(getattr(parser, "invoice_date", "") or ""),
        currency=str(getattr(parser, "currency", "EUR") or "EUR"),
        payment_days=int(getattr(parser, "payment_days", 30) or 30),
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
                    invoice_date=str(getattr(doc, "invoice_date", "") or ""),
                    currency=str(
                        getattr(doc, "currency", None)
                        or getattr(parser, "currency", "EUR")
                        or "EUR"
                    ),
                    payment_days=int(getattr(doc, "payment_days", None) or getattr(parser, "payment_days", 30) or 30),
                )
            )
        if not results:
            raise ValueError(f"No line items extracted for {parser.vendor_name}")
        return _spread_pack_freight(results)

    return [parse_invoice(pdf_path, transport_cost=transport_cost, factory=factory)]


def _spread_pack_freight(results: list[ParseResult]) -> list[ParseResult]:
    """Give every positive invoice in a pack its share of the freight.

    The freight sits on one PDF. That purchase document keeps the full amount,
    so it still matches the PDF. The warehouse value of each invoice uses only
    its share, proportional to the goods. The first warehouse document is then
    lower than its invoice, and the later ones are higher.
    """
    if len(results) < 2:
        return results
    pack = round(sum(item.transport_cost for item in results if not item.transport_is_external), 2)
    if pack <= 0:
        return results
    goods: list[float] = []
    for item in results:
        if item.rows.empty or "Value" not in item.rows.columns:
            goods.append(0.0)
        else:
            goods.append(round(float(item.rows["Value"].sum()), 2))
    base = round(sum(value for value in goods if value > 0), 2)
    if base <= 0:
        return results
    positive = [index for index, value in enumerate(goods) if value > 0]
    shares: dict[int, float] = {}
    running = 0.0
    for position, index in enumerate(positive):
        if position == len(positive) - 1:
            share = round(pack - running, 2)
        else:
            share = round(pack * goods[index] / base, 2)
            running = round(running + share, 2)
        shares[index] = share
    updated: list[ParseResult] = []
    for index, item in enumerate(results):
        own = 0.0 if item.transport_is_external else float(item.transport_cost)
        updated.append(
            replace(
                item,
                transport_cost=own,
                transport_is_external=False,
                warehouse_transport=shares.get(index, 0.0),
            )
        )
    return updated


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


def _invoice_frame(products_matrix, parser) -> pd.DataFrame:
    frame = pd.DataFrame(products_matrix, columns=SOURCE_COLUMNS)
    meta = list(getattr(parser, "line_meta", None) or [])
    if meta and len(meta) == len(frame):
        frame["Origin"] = [str(item.get("origin") or "") for item in meta]
        frame["Customs_code"] = [str(item.get("customs") or "") for item in meta]
    return frame


def _porcelain_from_china(origin: str, customs_code: str) -> bool:
    if "china" not in (origin or "").casefold():
        return False
    digits = "".join(char for char in (customs_code or "") if char.isdigit())
    return digits.startswith("6911")


def needs_manual_transport(vendor: str, transport_cost: float) -> bool:
    return vendor in VENDORS_REQUIRING_TRANSPORT and transport_cost <= 0.0


@dataclass(frozen=True)
class BufferLine:
    code: str
    qty: int
    unit_price: float
    value: float
    inne: float
    description: str
    duty: float = 0.0


@dataclass(frozen=True)
class BufferPrices:
    """Invoice lines for a purchase document, with external transport kept aside.

    The document total follows the PDF. External transport is a per-unit
    amount for the product card field 'inne', so the warehouse cost is higher
    while the saved invoice still matches the contractor's document.
    """

    lines: list[BufferLine]
    document_total: float
    header_discount: float
    transport: float
    matched: bool
    duty: float = 0.0


def prices_for_buffer(
    df: pd.DataFrame,
    pdf_total_amount: float,
    transport_cost: float = 0.0,
    *,
    transport_is_external: bool = False,
    warehouse_transport: float | None = None,
) -> BufferPrices:
    if df.empty:
        raise ValueError("No rows to format")
    working = drop_zero_rows(df)
    if "Value" not in working.columns:
        raise ValueError("No rows to format")
    goods = float(working["Value"].sum())
    if goods <= 0:
        raise ValueError("Sum of product values is 0")

    header_discount = 0.0
    diff = round(float(pdf_total_amount) - goods, 2)
    if diff < -0.10:
        header_discount = abs(diff)

    external = float(transport_cost) if transport_is_external else 0.0
    included_transport = 0.0 if transport_is_external else float(transport_cost)
    document_total = round(goods - header_discount + included_transport, 2)
    # "inne" is the gap between the purchase document and the warehouse value.
    # A pack share smaller than the freight printed on this invoice is negative.
    if warehouse_transport is None:
        inne_total = external
    else:
        inne_total = round(float(warehouse_transport) - included_transport, 2)

    coefficient = (document_total - goods) / goods
    price_rows: list[dict] = []
    inne_rows: list[dict] = []
    meta: list[tuple[str, str, str, str]] = []
    for _, row in working.iterrows():
        qty = int(row["Qty_shipped"])
        if qty <= 0:
            continue
        allocated = float(row["Value"]) * (1.0 + coefficient)
        price_rows.append({"Ilość": qty, "Cena jednostkowa": round(allocated / qty, 4)})
        share = float(row["Value"]) / goods * inne_total
        inne_rows.append({"Ilość": qty, "Cena jednostkowa": round(share / qty, 4) if inne_total else 0.0})
        meta.append(
            (
                str(row["Product_code"]),
                str(row.get("Description") or ""),
                str(row.get("Origin") or ""),
                str(row.get("Customs_code") or ""),
            )
        )

    if not price_rows:
        raise ValueError("No positive-qty rows after cleanup")

    _sum, exact = align_unit_prices_to_invoice_total(price_rows, document_total)
    inne_exact = True
    if inne_total:
        _inne_sum, inne_exact = align_unit_prices_to_invoice_total(inne_rows, round(inne_total, 2))

    duty_per_unit = [0.0] * len(meta)
    qualifying_indexes: list[int] = []
    qualifying_rows: list[dict] = []
    duty_base = 0.0
    for index, (_code, _description, origin, customs) in enumerate(meta):
        if not _porcelain_from_china(origin, customs):
            continue
        unit = float(price_rows[index]["Cena jednostkowa"])
        inne = float(inne_rows[index]["Cena jednostkowa"])
        qty = int(price_rows[index]["Ilość"])
        duty_base += (unit + inne) * qty
        qualifying_indexes.append(index)
        qualifying_rows.append(
            {"Ilość": qty, "Cena jednostkowa": round((unit + inne) * CHINA_PORCELAIN_ANTIDUMPING_RATE, 4)}
        )
    duty_exact = True
    if qualifying_rows:
        _duty_sum, duty_exact = align_unit_prices_to_invoice_total(
            qualifying_rows, round(duty_base * CHINA_PORCELAIN_ANTIDUMPING_RATE, 2)
        )
        for slot, index in enumerate(qualifying_indexes):
            duty_per_unit[index] = float(qualifying_rows[slot]["Cena jednostkowa"])

    lines = [
        BufferLine(
            code=code,
            qty=int(price_rows[index]["Ilość"]),
            unit_price=float(price_rows[index]["Cena jednostkowa"]),
            value=round(float(price_rows[index]["Cena jednostkowa"]) * int(price_rows[index]["Ilość"]), 2),
            inne=float(inne_rows[index]["Cena jednostkowa"]),
            description=description,
            duty=duty_per_unit[index],
        )
        for index, (code, description, _origin, _customs) in enumerate(meta)
    ]
    return BufferPrices(
        lines=lines,
        document_total=document_total,
        header_discount=header_discount,
        transport=round(inne_total, 2),
        matched=exact and inne_exact and duty_exact,
        duty=round(sum(line.duty * line.qty for line in lines), 2),
    )
