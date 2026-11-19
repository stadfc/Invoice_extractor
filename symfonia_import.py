"""Check invoice codes in Symfonia and write a WNT document to the buffer.

External transport is not part of the invoice currency total. It is stored on
each product as 'inne' and included in the złoty line value, so the warehouse
receipt is (goods + transport) times the typed exchange rate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote

from exchange_rates import RateError, rate_for
from pipeline import BufferPrices, prices_for_buffer
from symfonia_api import SymfoniaError, SymfoniaSession, api_version

# Contractor shortcut and code prefix, taken from the quoting app's supplier list.
VENDORS = {
    "APS": ("APS", "AP-"),
    "Bonna": ("Bonna", "BN-"),
    "Bormioli Luigi": ("BORMIOLI", "BL-"),
    "Churchill": ("Churchill", "CH-"),
    "Contacto": ("CONTACTO", "CO-"),
    "Karlowsky": ("KARLOWSKY", "KAR-"),
    "Leone": ("LEONE", "LE-"),
    "Mesa Ceramics": ("MESA EUROPA LDA", "KJ-"),
    "Pintinox": ("Pinti", "PI-"),
    "Sola Swiss": ("SOLA SWISS", "SS-"),
}
DOCUMENT_TYPE = "WNT"
DOCUMENT_SERIES = "sWNT"
DEPARTMENT = "HAN"
PAYMENT_FORM_ID = 65888
REGISTRIES = {"PLN": "BANK", "EUR": "BANK EUR", "GBP": "BANK GBP"}
VAT_ON_DOCUMENT = "NP"


@dataclass(frozen=True)
class CodeStatus:
    code: str
    present: bool
    name: str


@dataclass(frozen=True)
class BufferResult:
    number: str
    document_id: int | None
    created_codes: list[str]
    document_total: float
    currency: str
    transport: float


def card_name(description: str) -> str:
    name = re.split(r"\s+Lotto:", description or "", maxsplit=1)[0].strip()
    name = re.sub(r"\s+", " ", name)
    return (name or "Towar")[:200]


def check_codes(session: SymfoniaSession, codes: list[str]) -> list[CodeStatus]:
    found: list[CodeStatus] = []
    seen: set[str] = set()
    for raw in codes:
        code = (raw or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        product = _product(session, code)
        if product is None:
            found.append(CodeStatus(code, False, ""))
        else:
            found.append(CodeStatus(code, True, str(product.get("Name") or "").strip()))
    return found


def save_wnt_buffer(
    session: SymfoniaSession,
    *,
    vendor: str,
    currency: str,
    invoice_number: str,
    invoice_date: str,
    prices: BufferPrices,
    create_missing: bool,
    payment_days: int = 30,
) -> BufferResult:
    contractor, prefix = _vendor(vendor)
    ccy = (currency or "EUR").strip().upper() or "EUR"
    registry = REGISTRIES.get(ccy)
    if registry is None:
        raise SymfoniaError(f"Brak rejestru płatności dla waluty {ccy}.")
    _require_contractor(session, contractor)

    statuses = check_codes(session, [line.code for line in prices.lines])
    missing = [item.code for item in statuses if not item.present]
    present = [item.code for item in statuses if item.present]
    template = None
    if missing:
        if not create_missing:
            raise SymfoniaError("Brakujące kody: " + ", ".join(missing))
        if not present:
            raise SymfoniaError(
                f"Żaden produkt {prefix} z tej faktury nie jest w kartotece, więc nie ma wzoru nowej karty."
            )
        template = _product(session, present[0])
        if template is None:
            raise SymfoniaError(f"Nie udało się odczytać wzoru {present[0]}.")

    try:
        rate = rate_for(ccy)
    except RateError as exc:
        raise SymfoniaError(str(exc)) from exc
    created: list[str] = []
    by_code = {line.code: line for line in prices.lines}
    for code in missing:
        line = by_code[code]
        _create_product(session, template, line, ccy, rate)
        created.append(code)

    payload = _document_payload(
        contractor=contractor,
        currency=ccy,
        registry=registry,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        prices=prices,
        rate=rate,
        vendor=vendor,
        payment_days=payment_days,
    )
    _status, raw = session.call("POST", f"/api/{api_version()}/PurchasesIssue/New/false", payload)
    number, document_id = _created_document(raw)
    # The purchase document stores the invoice in its own currency. The warehouse
    # document values the goods from the card, so the PLN purchase price has to
    # be written after the document and must already include transport.
    try:
        for line in prices.lines:
            product = _product(session, line.code)
            if product is None:
                raise SymfoniaError(f"Po zapisie dokumentu brak kodu {line.code}.")
            _update_purchase_price(session, product, line.unit_price, line.inne, ccy, rate, line.duty)
    except SymfoniaError as exc:
        raise SymfoniaError(
            f"Dokument {number} jest już w buforze, ale nie udało się ustawić cen na kartach. {exc}"
        ) from exc
    return BufferResult(
        number=number,
        document_id=document_id,
        created_codes=created,
        document_total=prices.document_total,
        currency=ccy,
        transport=prices.transport,
    )


def purchase_document(vendor: str) -> tuple[str, str, str]:
    """Document type, series and VAT code for this supplier.

    Bonna is a customs import (DIM). The other suppliers are intra-community WNT.
    """
    if vendor == "Bonna":
        return "DIM", "sDIM", "23%"
    return DOCUMENT_TYPE, DOCUMENT_SERIES, VAT_ON_DOCUMENT


def _vendor(vendor: str) -> tuple[str, str]:
    chosen = VENDORS.get(vendor)
    if chosen is None:
        raise SymfoniaError(f"Dostawca {vendor} nie ma ustawionego kodu kontrahenta WNT.")
    return chosen


def _product(session: SymfoniaSession, code: str) -> dict | None:
    code = (code or "").strip()
    if not code:
        return None
    # A slash in the code becomes part of the URL path. Symfonia then answers
    # 404 even though the card exists, so those codes are looked up by id.
    if "/" in code:
        product_id = _product_id(session, code)
        if product_id is None:
            return None
        return _product_by_id(session, product_id)
    return _product_by_id(session, quote(code, safe=""))


def _product_id(session: SymfoniaSession, code: str) -> int | None:
    _status, raw = session.call(
        "PATCH",
        f"/api/{api_version()}/Products/FilterSql",
        {"Code": {"Value": code, "Mode": "Equals"}},
    )
    try:
        data = json.loads(raw or "null")
    except json.JSONDecodeError:
        return None
    rows = data if isinstance(data, list) else []
    if isinstance(data, dict):
        rows = data.get("data") or data.get("Items") or []
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("Code") or "") == code and row.get("Id"):
            return int(row["Id"])
    return None


def _product_by_id(session: SymfoniaSession, product_ref: int | str) -> dict | None:
    try:
        _status, raw = session.call("GET", f"/api/{api_version()}/Products/{product_ref}")
    except SymfoniaError as exc:
        if exc.status == 404:
            return None
        raise
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and (data.get("Code") or data.get("Id")):
        return data
    return None


def _require_contractor(session: SymfoniaSession, code: str) -> None:
    encoded = quote(code, safe="")
    try:
        session.call("GET", f"/api/{api_version()}/Contractors/{encoded}")
    except SymfoniaError as exc:
        if exc.status == 404:
            raise SymfoniaError(f"Brak kontrahenta {code} w Symfonii.") from exc
        raise


def _pln_purchase(unit_price: float, inne: float, rate: float, duty: float = 0.0) -> float:
    """PLN purchase price is (invoice unit + transport + duty) times the typed rate."""
    return round((float(unit_price) + float(inne) + float(duty)) * float(rate), 2)


def _card_purchase(unit_price: float, inne: float, rate: float, duty: float = 0.0) -> tuple[float, float, float, float]:
    """Currency purchase, CalcOther, CalcDuty and PLN purchase stored on the card.

    Symfonia rejects CalcOther below zero. When this invoice carries more freight
    than its warehouse share, that excess comes out of the purchase price.
    """
    unit = float(unit_price)
    other = float(inne)
    clo = float(duty)
    pln = _pln_purchase(unit, other, rate, clo)
    if other < 0:
        return round(unit + other, 4), 0.0, clo, pln
    return unit, other, clo, pln


def _price_update_body(
    product: dict, unit_price: float, inne: float, currency: str, rate: float, duty: float = 0.0
) -> dict:
    foreign = currency != "PLN"
    # A card rate of 1.0 is stored on every foreign product and is truthy, so it
    # must not win over the typed rate. Symfonia recalculates the PLN purchase
    # price from this rate; leaving 1.0 makes the warehouse value equal the invoice.
    used_rate = rate if foreign else 1.0
    currency_price, other, clo, pln = _card_purchase(unit_price, inne, used_rate, duty)
    body = {
        "SalePriceRecalculate": False,
        "CurrencyMode": bool(product.get("CurrencyMode")),
        "CurrencyRate": used_rate,
        "CurrencyRateWithoutConversion": used_rate,
        "PurchasePrice": {"Value": pln, "Currency": "PLN"},
        "PurchasePriceInCurrency": {"Value": currency_price, "Currency": currency},
        "CalcOther": {"Value": other, "Currency": currency},
        "CalcDuty": {"Value": clo, "Currency": currency},
        "SalePrices": list(product.get("SalePrices") or []),
    }
    base = product.get("BasePrice")
    if isinstance(base, dict) and base.get("Value") is not None:
        body["BasePrice"] = {"Value": base.get("Value"), "Currency": base.get("Currency") or ""}
    return body


def _create_product(session: SymfoniaSession, template: dict, line, currency: str, rate: float) -> None:
    vat = ((template.get("VatRate") or {}).get("Code") or "23%").strip()
    kind = ((template.get("Kind") or {}).get("Code") or "").strip()
    units = template.get("UnitsOfMeasurement") or {}
    unit = (units.get("DefaultUM") or units.get("RecordUM") or "szt").strip() or "szt"
    used_rate = rate if currency != "PLN" else 1.0
    currency_price, other, clo, pln = _card_purchase(line.unit_price, line.inne, used_rate, line.duty)
    payload = {
        "Active": True,
        "Code": line.code,
        "Name": card_name(line.description),
        "Type": "Article",
        "VatRate": {"Code": vat},
        "CurrencyMode": bool(template.get("CurrencyMode")),
        "CurrencyRate": used_rate,
        "CurrencyRateWithoutConversion": used_rate,
        "SalePriceRecalculate": False,
        "UnitsOfMeasurement": {
            "RecordUM": unit,
            "DefaultUM": unit,
            "DisplayUM": unit,
        },
        "PurchasePriceInCurrency": {"Value": currency_price, "Currency": currency},
        "CalcOther": {"Value": other, "Currency": currency},
        "CalcDuty": {"Value": clo, "Currency": currency},
        "PurchasePrice": {"Value": pln, "Currency": "PLN"},
    }
    if kind:
        payload["Kind"] = {"Code": kind}
    base = template.get("BasePrice") or {}
    base_value = float(base.get("Value") or 0)
    template_currency = float((template.get("PurchasePriceInCurrency") or {}).get("Value") or 0)
    if base_value > 0 and template_currency > 0:
        payload["BasePrice"] = {
            "Value": round(line.unit_price * base_value / template_currency, 2),
            "Currency": (base.get("Currency") or currency),
        }
    session.call("POST", f"/api/{api_version()}/Products/Create", payload)


def _update_purchase_price(
    session: SymfoniaSession, product: dict, unit_price: float, inne: float, currency: str, rate: float, duty: float = 0.0
) -> None:
    code = str(product.get("Code") or "").strip()
    body = _price_update_body(product, unit_price, inne, currency, rate, duty)
    # The numeric id keeps a slash in the code out of the URL.
    ref = product.get("Id") or quote(code, safe="")
    session.call("PUT", f"/api/{api_version()}/ProductPrices/Update/{ref}", body)


def _document_payload(
    *,
    contractor: str,
    currency: str,
    registry: str,
    invoice_number: str,
    invoice_date: str,
    prices: BufferPrices,
    rate: float,
    vendor: str = "",
    payment_days: int = 30,
) -> dict:
    party = {"Code": contractor, "RecalculatePrices": False}
    positions = []
    # Value is the line amount in PLN. PriceValue is the unit price in the
    # invoice currency. Sending the euro amount in Value makes Symfonia store
    # that same number as the złoty value, so the warehouse receipt copies it.
    used_rate = rate if currency != "PLN" else 1.0
    doc_type, series, vat = purchase_document(vendor)
    for line in prices.lines:
        position = {
            "Code": line.code,
            "Quantity": line.qty,
            "UnitOfMeasurement": "szt",
            "PriceValue": line.unit_price,
            "Value": round((line.unit_price + line.inne) * used_rate * line.qty, 2),
            "VatRate": {"Code": vat},
        }
        # Duty is the PLN customs amount. Value stays the goods-plus-transport
        # amount, so the two are not added twice on the warehouse receipt.
        duty_pln = round(line.duty * used_rate * line.qty, 2)
        if duty_pln:
            position["Duty"] = duty_pln
        positions.append(position)
    payload = {
        "TypeCode": doc_type,
        "Series": series,
        "Department": DEPARTMENT,
        "PaymentRegistry": {"Code": registry},
        "PaymentFormId": PAYMENT_FORM_ID,
        "PriceKind": "Net",
        "Seller": party,
        "Deliverer": party,
        "ForeignDocumentNumber": (invoice_number or "")[:80],
        "Description": f"{doc_type} {contractor} {invoice_number}".strip()[:200],
        "Note": "invoice-extractor",
        "Positions": positions,
    }
    if currency != "PLN":
        payload["Currency"] = currency
        payload["CurrencyRate"] = rate
        # Symfonia otherwise looks up the CIT rate for the invoice day and rejects
        # the document when that day is missing from its table.
        payload["CurrencyRateCIT"] = rate
    if invoice_date:
        payload["IssueDate"] = invoice_date
        payload["PurchaseDate"] = invoice_date
        payload["ReceiveDate"] = invoice_date
        payload["ForeignDocumentDate"] = invoice_date
        try:
            issued = date.fromisoformat(invoice_date)
        except ValueError:
            issued = None
        if issued is not None:
            payload["MaturityDate"] = (issued + timedelta(days=max(int(payment_days), 0))).isoformat()
    return payload


def _created_document(raw: str) -> tuple[str, int | None]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SymfoniaError("Symfonia nie zwróciła numeru dokumentu.") from exc
    number = ""
    document_id = None
    if isinstance(data, dict):
        number = str(data.get("DocumentNumber") or "").strip()
        if data.get("Id"):
            document_id = int(data["Id"])
    if not number:
        raise SymfoniaError("Symfonia nie zwróciła numeru dokumentu.")
    return number, document_id
