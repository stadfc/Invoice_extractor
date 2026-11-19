"""Read own purchase orders (ZWW) from the Symfonia WebAPI. Nothing is written."""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from urllib.parse import quote

from order_match import OwnOrderSnapshot
from symfonia_api import API_VERSION, SymfoniaError, SymfoniaSession

# DocumentStatusText for a fully finished order. Partial realization stays open.
_CLOSED_TEXTS = {"ZREALIZOWANE", "ZAMKNIĘTE", "ZAMKNIETE", "ANULOWANE", "ANULOWANY"}
_CLOSED_STATUS = {"Realized", "Closed"}
# Finished orders seen in this program run, by order id -> when it was read. Most orders of the
# last 12 months are finished; a later check skips their two WebAPI calls for CACHE_SECONDS.
# Open orders are always read again, so a quantity just corrected in Symfonia is seen at once.
CACHE_SECONDS = 1800
_FINISHED: dict[int, float] = {}


def read_open_orders(
    session: SymfoniaSession,
    seller_code: str,
    today: date | None = None,
) -> list[OwnOrderSnapshot]:
    """Open ZWW and ZMW of this seller from the last 12 months."""
    seller = (seller_code or "").strip()
    if not seller:
        raise SymfoniaError("Brak kodu kontrahenta do wyszukania zamówień.")
    end = today or date.today()
    start = end - timedelta(days=365)
    path = (
        f"/api/{API_VERSION}/OwnOrders/Filter/{quote(seller, safe='')}"
        f"/{start.isoformat()}/{end.isoformat()}"
    )
    _status, raw = session.call("GET", path)
    rows = _json_list(raw)
    orders: list[OwnOrderSnapshot] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("TypeCode") or "") not in {"ZWW", "ZMW"}:
            continue
        if row.get("Buffer") is True or row.get("Active") is False or _is_canceled(row.get("Canceled")):
            continue
        order_id = row.get("Id")
        number = str(row.get("DocumentNumber") or "").strip()
        if not order_id or not number:
            continue
        quantities = _open_order_quantities(session, order_id)
        if quantities is None:
            continue
        issued = str(row.get("IssueDate") or "")[:10]
        orders.append(OwnOrderSnapshot(number, issued, quantities))
    return orders


def load_purchase_lines(session: SymfoniaSession, document_number: str) -> tuple[str, list[tuple[str, float]]]:
    """Contractor code and invoice lines of a purchase already stored in Symfonia."""
    number = (document_number or "").strip()
    if not number:
        raise SymfoniaError("Podaj numer dokumentu.")
    encoded = quote(number, safe="")
    document = None
    for source in ("FromBuffer", "Issued"):
        try:
            _status, raw = session.call("GET", f"/api/{API_VERSION}/Purchases/{source}/{encoded}")
        except SymfoniaError as exc:
            if exc.status == 404:
                continue
            raise
        document = json.loads(raw or "null")
        break
    if not isinstance(document, dict):
        raise SymfoniaError(f"Nie ma dokumentu {number} w buforze ani w wystawionych.")
    seller_id = document.get("SellerId") or document.get("DelivererId")
    if not seller_id:
        raise SymfoniaError(f"Dokument {number} nie ma kontrahenta.")
    _status, raw = session.call("GET", f"/api/{API_VERSION}/Contractors/{seller_id}")
    contractor = json.loads(raw or "null")
    code = ""
    if isinstance(contractor, dict):
        code = str(contractor.get("Code") or "").strip()
    if not code:
        raise SymfoniaError(f"Nie udało się odczytać kodu kontrahenta dokumentu {number}.")
    lines = [
        (str(position.get("ProductCode") or ""), float(position.get("Quantity") or 0))
        for position in (document.get("Positions") or [])
        if isinstance(position, dict)
    ]
    return code, lines


def _open_order_quantities(session: SymfoniaSession, order_id) -> dict[str, float] | None:
    """Ordered quantity per product, or None for a finished order."""
    key = int(order_id)
    seen = _FINISHED.get(key)
    if seen is not None and time.monotonic() - seen < CACHE_SECONDS:
        return None
    _status, raw = session.call("GET", f"/api/{API_VERSION}/OwnOrders/{order_id}")
    detail = json.loads(raw or "null")
    # A settled order is finished: no need to ask for its status separately.
    if (isinstance(detail, dict) and detail.get("Settled") is True) or _status_is_closed(session, order_id):
        _FINISHED[key] = time.monotonic()
        return None
    return _position_quantities(detail)


def _position_quantities(detail) -> dict[str, float]:
    totals: dict[str, float] = {}
    positions = detail.get("Positions") if isinstance(detail, dict) else None
    for position in positions or []:
        if not isinstance(position, dict):
            continue
        code = str(position.get("ProductCode") or "").strip()
        if not code:
            continue
        totals[code] = totals.get(code, 0.0) + abs(float(position.get("Quantity") or 0))
    return {code: qty for code, qty in totals.items() if qty > 0}


def _status_is_closed(session: SymfoniaSession, order_id) -> bool:
    try:
        _status, raw = session.call("GET", f"/api/{API_VERSION}/OwnOrders/Status/{order_id}")
    except SymfoniaError:
        return False
    info = json.loads(raw or "null")
    if not isinstance(info, dict):
        return False
    text = str(info.get("DocumentStatusText") or "").strip().upper()
    if text in _CLOSED_TEXTS:
        return True
    status = info.get("DocumentStatus")
    return isinstance(status, str) and status in _CLOSED_STATUS


def _is_canceled(value) -> bool:
    if value in (None, "", 0, "0", "Other", False):
        return False
    return True


def _json_list(raw: str) -> list:
    try:
        data = json.loads(raw or "null")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
