"""Compare an invoice with own purchase orders. No Symfonia calls."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OwnOrderSnapshot:
    number: str
    issue_date: str
    quantities: dict[str, float]


@dataclass(frozen=True)
class WaitingElsewhere:
    number: str
    issue_date: str
    quantity: float


@dataclass(frozen=True)
class MissingGoods:
    code: str
    quantity: float
    elsewhere: tuple[WaitingElsewhere, ...]


@dataclass(frozen=True)
class QuantitySurplus:
    code: str
    order_quantity: float
    invoice_quantity: float
    elsewhere: tuple[WaitingElsewhere, ...]


@dataclass(frozen=True)
class MatchReport:
    proposed_number: str | None
    proposed_date: str
    headline: str
    missing: tuple[MissingGoods, ...]
    surplus: tuple[QuantitySurplus, ...]
    only_on_order: tuple[tuple[str, float], ...]


def sum_quantities(lines: list[tuple[str, float]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for code, qty in lines:
        name = (code or "").strip()
        if not name:
            continue
        amount = abs(float(qty))
        if amount <= 0:
            continue
        totals[name] = totals.get(name, 0.0) + amount
    return totals


def match_invoice_to_orders(
    invoice_lines: list[tuple[str, float]],
    orders: list[OwnOrderSnapshot],
) -> MatchReport:
    invoice = sum_quantities(invoice_lines)
    prepared = [
        OwnOrderSnapshot(order.number, (order.issue_date or "")[:10], sum_quantities(list(order.quantities.items())))
        for order in orders
        if (order.number or "").strip()
    ]
    proposed = _best_order(invoice, prepared)
    if proposed is None:
        return MatchReport(
            proposed_number=None,
            proposed_date="",
            headline="Żadne otwarte zamówienie tego dostawcy nie ma wspólnych towarów z fakturą.",
            missing=(),
            surplus=(),
            only_on_order=(),
        )

    missing: list[MissingGoods] = []
    surplus: list[QuantitySurplus] = []
    for code, qty in sorted(invoice.items()):
        on_order = proposed.quantities.get(code, 0.0)
        waiting = _older_waiting(prepared, proposed, code)
        if on_order <= 0:
            missing.append(MissingGoods(code, qty, waiting))
        elif qty > on_order + 0.0001:
            surplus.append(QuantitySurplus(code, on_order, qty, waiting))

    only_on_order = tuple(
        (code, qty)
        for code, qty in sorted(proposed.quantities.items())
        if code not in invoice and qty > 0
    )
    count = len(missing) + len(surplus)
    if count == 0:
        headline = f"Faktura da się powiązać z {proposed.number} bez zmian"
    else:
        headline = f"Przed powiązaniem dopisz do {proposed.number} {count} {_pozycji(count)}"
    return MatchReport(
        proposed_number=proposed.number,
        proposed_date=proposed.issue_date,
        headline=headline,
        missing=tuple(missing),
        surplus=tuple(surplus),
        only_on_order=only_on_order,
    )


def _older_waiting(
    orders: list[OwnOrderSnapshot], proposed: OwnOrderSnapshot, code: str
) -> tuple[WaitingElsewhere, ...]:
    waiting = [
        WaitingElsewhere(order.number, order.issue_date, order.quantities[code])
        for order in orders
        if order.number != proposed.number
        and order.issue_date < proposed.issue_date
        and order.quantities.get(code, 0.0) > 0
    ]
    waiting.sort(key=lambda item: (item.issue_date, item.number))
    return tuple(waiting)


def _best_order(invoice: dict[str, float], orders: list[OwnOrderSnapshot]) -> OwnOrderSnapshot | None:
    best: OwnOrderSnapshot | None = None
    best_shared = 0
    for order in orders:
        shared = sum(1 for code in invoice if order.quantities.get(code, 0.0) > 0)
        if shared <= 0:
            continue
        if best is None or shared > best_shared or (
            shared == best_shared and (order.issue_date, order.number) > (best.issue_date, best.number)
        ):
            best = order
            best_shared = shared
    return best


def export_rows(report: MatchReport) -> list[dict]:
    """Table behind the clipboard copy and the Excel file."""
    order = report.proposed_number or ""
    rows: list[dict] = []
    for item in report.missing:
        rows.append(
            {
                "Rodzaj": "Dopisać do zamówienia",
                "Kod": item.code,
                "Ilość na fakturze": item.quantity,
                "Ilość w zamówieniu": 0,
                "Polecenie": f"dopisz do {order}" if order else "dopisz do zamówienia",
                "Starsze ZWW/ZMW": _waiting_text(item.elsewhere),
            }
        )
    for item in report.surplus:
        rows.append(
            {
                "Rodzaj": "Nadwyżka ilości",
                "Kod": item.code,
                "Ilość na fakturze": item.invoice_quantity,
                "Ilość w zamówieniu": item.order_quantity,
                "Polecenie": (
                    f"podnieś ilość w {order} z {_qty_text(item.order_quantity)} "
                    f"do {_qty_text(item.invoice_quantity)}"
                ),
                "Starsze ZWW/ZMW": _waiting_text(item.elsewhere),
            }
        )
    for code, qty in report.only_on_order:
        rows.append(
            {
                "Rodzaj": "Tylko na zamówieniu",
                "Kod": code,
                "Ilość na fakturze": 0,
                "Ilość w zamówieniu": qty,
                "Polecenie": "nie blokuje powiązania",
                "Starsze ZWW/ZMW": "",
            }
        )
    return rows


def clipboard_text(report: MatchReport, document_number: str = "") -> str:
    lines = [report.headline]
    detail = _export_detail(report, document_number)
    if detail:
        lines.append(detail)
    lines.append("")
    headers = list(EXPORT_COLUMNS)
    lines.append("\t".join(headers))
    for row in export_rows(report):
        lines.append("\t".join(_cell(row[name]) for name in headers))
    return "\n".join(lines)


EXPORT_COLUMNS = (
    "Rodzaj",
    "Kod",
    "Ilość na fakturze",
    "Ilość w zamówieniu",
    "Polecenie",
    "Starsze ZWW/ZMW",
)


def _export_detail(report: MatchReport, document_number: str) -> str:
    parts = []
    if document_number:
        parts.append(f"Dokument {document_number}.")
    if report.proposed_number:
        when = _pl_date(report.proposed_date)
        dated = f" z {when}" if when else ""
        parts.append(f"Proponowane zamówienie: {report.proposed_number}{dated}.")
    return " ".join(parts)


def _waiting_text(waiting: tuple[WaitingElsewhere, ...]) -> str:
    if not waiting:
        return "nie ma na starszych ZWW/ZMW"
    return "; ".join(f"{item.number} ({_qty_text(item.quantity)} szt.)" for item in waiting)


def _cell(value) -> str:
    if isinstance(value, float):
        return _qty_text(value)
    return str(value)


def _qty_text(value: float) -> str:
    if abs(value - round(value)) < 0.0001:
        return str(int(round(value)))
    return f"{value:.2f}".replace(".", ",")


def _pl_date(iso: str) -> str:
    text = (iso or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text.split("-")
        return f"{day}.{month}.{year}"
    return text


def _pozycji(count: int) -> str:
    if count == 1:
        return "pozycję"
    remainder = count % 100
    if 12 <= remainder <= 14:
        return "pozycji"
    if count % 10 in (2, 3, 4):
        return "pozycje"
    return "pozycji"
