"""Symfonia WebAPI session. The token is read from symfonia.env next to this file.

symfonia.env may also set SYMFONIA_WEBAPI_VERSION, the path prefix (api/<version>/...),
when a WebAPI update drops the default one. Check the connection after an update with:

    python symfonia_api.py [PRODUCT_CODE]
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API_VERSION = "v2026.3"
CLIENT_ID = "invoice-extractor"
DEFAULT_URL = "https://www.kjgastro.com.pl:9000"
ENV_FILE = Path(__file__).with_name("symfonia.env")


class SymfoniaError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _load_env_file(path: Path) -> None:
    try:
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SymfoniaError(f"Nie można odczytać {path.name}.") from exc
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def api_version() -> str:
    """Path prefix of every WebAPI call: SYMFONIA_WEBAPI_VERSION from symfonia.env, else the default."""
    _load_env_file(ENV_FILE)
    return (os.environ.get("SYMFONIA_WEBAPI_VERSION") or "").strip().strip("/") or DEFAULT_API_VERSION


def api_settings() -> tuple[str, str]:
    _load_env_file(ENV_FILE)
    url = (os.environ.get("SYMFONIA_WEBAPI_URL") or DEFAULT_URL).strip().rstrip("/")
    token = (os.environ.get("SYMFONIA_WEBAPI_TOKEN") or "").strip()
    if not token:
        raise SymfoniaError("Brak klucza WebAPI Symfonii.")
    return url, token


def _error_text(status: int, raw: str) -> str:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = None
    message = ""
    if isinstance(data, dict):
        message = str(data.get("Message") or data.get("message") or data.get("ExceptionMessage") or "")
        errors = data.get("ModelState") or data.get("errors") or data.get("Errors")
        if isinstance(errors, dict):
            parts = []
            for key, value in errors.items():
                if isinstance(value, list):
                    parts.append(f"{key}: {', '.join(str(item) for item in value)}")
                else:
                    parts.append(f"{key}: {value}")
            if parts:
                message = (message + " " + " ".join(parts)).strip()
    text = " ".join((message or raw or "").split())
    if len(text) > 400:
        text = text[:400] + "…"
    if not text:
        return f"Symfonia odrzuciła wywołanie ({status})."
    return text


class SymfoniaSession:
    def __init__(self):
        self.url, self.token = api_settings()
        self.session = ""

    def __enter__(self):
        _status, raw = self._request(
            f"/api/{api_version()}/Sessions/OpenNewSession/{CLIENT_ID}",
            f"Application {self.token}",
        )
        self.session = _session_id(raw)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self._request(f"/api/{api_version()}/Sessions/CloseSession", f"Session {self.session}")
        except SymfoniaError:
            pass
        return False

    def call(self, method: str, path: str, body=None):
        return self._request(path, f"Session {self.session}", method, body)

    def _request(self, path: str, authorization: str, method: str = "GET", body=None):
        headers = {"Accept": "application/json", "X-Client-Id": CLIENT_ID, "Authorization": authorization}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise SymfoniaError(_error_text(exc.code, raw), status=exc.code) from exc
        except URLError as exc:
            raise SymfoniaError("Usługa Symfonia WebAPI nie odpowiada.") from exc


def _session_id(raw: str) -> str:
    text = (raw or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = text.strip('"')
    if not isinstance(parsed, str) or not parsed:
        raise SymfoniaError("Symfonia nie otworzyła sesji.")
    return parsed


def check(code: str = "") -> int:
    """Open a session and, with a product code, read that product's card. 0 = works."""
    version = api_version()
    try:
        url, _token = api_settings()
    except SymfoniaError as exc:
        print(f"BŁĄD: {exc}")
        return 2
    print(f"WebAPI {url}, wersja ścieżek {version}")
    try:
        with SymfoniaSession() as session:
            print("OK    sesja otwarta")
            if code:
                _status, raw = session.call(
                    "PATCH", f"/api/{version}/Products/FilterSql", {"Code": {"Value": code, "Mode": "Equals"}}
                )
                rows = json.loads(raw or "null")
                if isinstance(rows, dict):
                    rows = rows.get("data") or []
                found = [row for row in rows or [] if isinstance(row, dict) and row.get("Code") == code]
                if not found:
                    print(f"BŁĄD  towar {code} nie znaleziony")
                    return 1
                session.call("GET", f"/api/{version}/Products/{int(found[0]['Id'])}")
                print(f"OK    karta towaru {code} odczytana")
    except (SymfoniaError, ValueError, KeyError, TypeError) as exc:
        print(f"BŁĄD: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(check(sys.argv[1] if len(sys.argv) > 1 else ""))
