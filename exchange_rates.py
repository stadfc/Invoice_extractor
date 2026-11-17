"""Exchange rates typed in the extractor. PLN is always 1."""

from __future__ import annotations

import json
from pathlib import Path

CURRENCIES = ("EUR", "USD", "GBP", "PLN")
RATES_PATH = Path(__file__).with_name("exchange_rates.json")


class RateError(Exception):
    pass


def load_rates(path: Path | None = None) -> dict[str, float | None]:
    target = path or RATES_PATH
    found: dict[str, float | None] = {code: None for code in CURRENCIES}
    found["PLN"] = 1.0
    if not target.is_file():
        return found
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return found
    if not isinstance(raw, dict):
        return found
    for code in ("EUR", "USD", "GBP"):
        value = _positive(raw.get(code))
        if value is not None:
            found[code] = value
    return found


def save_rates(rates: dict[str, float | None], path: Path | None = None) -> None:
    target = path or RATES_PATH
    payload = {"PLN": 1.0}
    for code in ("EUR", "USD", "GBP"):
        value = _positive(rates.get(code))
        if value is not None:
            payload[code] = value
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def rate_for(currency: str, path: Path | None = None) -> float:
    code = (currency or "EUR").strip().upper() or "EUR"
    if code == "PLN":
        return 1.0
    if code not in CURRENCIES:
        raise RateError(f"Brak pola kursu dla waluty {code}.")
    value = load_rates(path).get(code)
    if value is None:
        raise RateError(f"Uzupełnij kurs {code} w ustawieniach (Kursy).")
    return value


def parse_rate(raw: str) -> float | None:
    text = (raw or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise RateError("Kurs musi być liczbą większą od zera.") from exc
    if value <= 0:
        raise RateError("Kurs musi być liczbą większą od zera.")
    return value


def _positive(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number
