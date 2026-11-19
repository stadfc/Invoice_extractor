import unittest
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exchange_rates import RateError, load_rates, parse_rate, rate_for, save_rates
from pipeline import BufferLine, BufferPrices
from symfonia_import import _document_payload, _price_update_body, check_codes
from symfonia_api import SymfoniaError


class FakeSession:
    def __init__(self, present):
        self.present = set(present)

    def call(self, method, path, body=None):
        code = path.rsplit("/", 1)[-1]
        if code not in self.present:
            raise SymfoniaError("missing", status=404)
        return 200, '{"Code": "%s", "Name": "Taca"}' % code


class CodeCheckTests(unittest.TestCase):
    def test_missing_code_is_reported(self):
        report = check_codes(FakeSession({"LE-S0062"}), ["LE-S0062", "LE-S0062", "LE-NEW"])
        self.assertEqual([(item.code, item.present) for item in report], [
            ("LE-S0062", True),
            ("LE-NEW", False),
        ])
        self.assertEqual(report[0].name, "Taca")
        self.assertEqual(report[1].name, "")

    def test_slash_in_the_code_is_looked_up_by_id(self):
        class SlashSession:
            def __init__(self):
                self.paths = []

            def call(self, method, path, body=None):
                self.paths.append(path)
                if path.endswith("/Products/FilterSql"):
                    self.assert_body = body
                    return 200, '[{"Id": 128682, "Code": "BN-GNP1/2KVT"}]'
                if path.endswith("/Products/128682"):
                    return 200, '{"Id": 128682, "Code": "BN-GNP1/2KVT", "Name": "Wanna gastronomiczna"}'
                raise SymfoniaError("missing", status=404)

        session = SlashSession()
        report = check_codes(session, ["BN-GNP1/2KVT"])
        self.assertEqual([(item.code, item.present, item.name) for item in report], [
            ("BN-GNP1/2KVT", True, "Wanna gastronomiczna"),
        ])
        self.assertTrue(session.paths[0].endswith("/Products/FilterSql"))
        self.assertEqual(session.assert_body["Code"]["Value"], "BN-GNP1/2KVT")
        self.assertNotIn("%2F", session.paths[1])


class ExchangeRateTests(unittest.TestCase):
    def test_typed_rate_is_used_and_pln_stays_one(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "exchange_rates.json"
        save_rates({"EUR": parse_rate("4,27"), "GBP": None, "USD": 3.8}, path)
        stored = load_rates(path)
        self.assertEqual(stored["PLN"], 1.0)
        self.assertAlmostEqual(rate_for("EUR", path), 4.27)
        self.assertAlmostEqual(rate_for("USD", path), 3.8)
        self.assertEqual(rate_for("PLN", path), 1.0)
        with self.assertRaises(RateError):
            rate_for("GBP", path)

    def test_document_uses_the_typed_rate_for_cit(self):
        prices = BufferPrices(
            lines=[BufferLine("LE-A", 1, 10.0, 10.0, 0.0, "tray")],
            document_total=10.0,
            header_discount=0.0,
            transport=0.0,
            matched=True,
        )
        payload = _document_payload(
            contractor="LEONE",
            currency="EUR",
            registry="BANK EUR",
            invoice_number="000965/26B",
            invoice_date="2026-10-05",
            prices=prices,
            rate=4.27,
        )
        self.assertEqual(payload["CurrencyRate"], 4.27)
        self.assertEqual(payload["CurrencyRateCIT"], 4.27)
        self.assertEqual(payload["Positions"][0]["PriceValue"], 10.0)
        self.assertAlmostEqual(payload["Positions"][0]["Value"], 42.70)

    def test_warehouse_value_includes_transport_in_pln(self):
        prices = BufferPrices(
            lines=[BufferLine("LE-A", 2, 10.0, 20.0, 1.5, "tray")],
            document_total=20.0,
            header_discount=0.0,
            transport=3.0,
            matched=True,
        )
        payload = _document_payload(
            contractor="LEONE",
            currency="EUR",
            registry="BANK EUR",
            invoice_number="000965/26B",
            invoice_date="2026-10-05",
            prices=prices,
            rate=4.7,
        )
        position = payload["Positions"][0]
        self.assertEqual(position["PriceValue"], 10.0)
        self.assertAlmostEqual(position["Value"], 108.10)

    def test_pln_purchase_uses_the_typed_rate_not_the_card_rate(self):
        product = {
            "CurrencyMode": False,
            "CurrencyRate": 1.0,
            "CurrencyRateWithoutConversion": 1.0,
            "SalePrices": [{"Type": 1, "Value": 30.85}],
            "BasePrice": {"Value": 3.53, "Currency": "EUR"},
        }
        body = _price_update_body(product, 3.2301, 0.3016, "EUR", 4.7)
        self.assertEqual(body["CurrencyRate"], 4.7)
        self.assertEqual(body["CurrencyRateWithoutConversion"], 4.7)
        self.assertFalse(body["CurrencyMode"])
        self.assertFalse(body["SalePriceRecalculate"])
        self.assertEqual(body["SalePrices"], [{"Type": 1, "Value": 30.85}])
        self.assertAlmostEqual(body["PurchasePrice"]["Value"], 16.60)
        self.assertAlmostEqual(body["CalcOther"]["Value"], 0.3016)
        self.assertAlmostEqual(body["PurchasePriceInCurrency"]["Value"], 3.2301)

    def test_negative_inne_stays_out_of_calc_other(self):
        product = {
            "CurrencyMode": False,
            "CurrencyRate": 1.0,
            "SalePrices": [],
            "BasePrice": {"Value": 1.0, "Currency": "GBP"},
        }
        body = _price_update_body(product, 10.0, -1.5, "GBP", 5.5)
        self.assertEqual(body["CalcOther"]["Value"], 0.0)
        self.assertAlmostEqual(body["PurchasePriceInCurrency"]["Value"], 8.5)
        self.assertAlmostEqual(body["PurchasePrice"]["Value"], 46.75)

        prices = BufferPrices(
            lines=[BufferLine("CH-A", 1, 130.0, 130.0, -15.0, "bowl")],
            document_total=130.0,
            header_discount=0.0,
            transport=-15.0,
            matched=True,
        )
        payload = _document_payload(
            contractor="Churchill",
            currency="GBP",
            registry="BANK GBP",
            invoice_number="CD1",
            invoice_date="2026-10-16",
            prices=prices,
            rate=5.5,
        )
        position = payload["Positions"][0]
        self.assertEqual(position["PriceValue"], 130.0)
        self.assertAlmostEqual(position["Value"], 632.50)

    def test_import_document_keeps_duty_beside_the_goods_value(self):
        product = {
            "CurrencyMode": False,
            "CurrencyRate": 1.0,
            "SalePrices": [],
            "BasePrice": {"Value": 1.0, "Currency": "EUR"},
        }
        body = _price_update_body(product, 100.0, 10.0, "EUR", 4.7, 86.9)
        self.assertAlmostEqual(body["CalcDuty"]["Value"], 86.9)
        self.assertAlmostEqual(body["CalcOther"]["Value"], 10.0)
        self.assertAlmostEqual(body["PurchasePrice"]["Value"], 925.43)

        prices = BufferPrices(
            lines=[BufferLine("BN-CN", 1, 100.0, 100.0, 10.0, "bowl", 86.9)],
            document_total=100.0,
            header_discount=0.0,
            transport=10.0,
            matched=True,
            duty=86.9,
        )
        payload = _document_payload(
            contractor="Bonna",
            currency="EUR",
            registry="BANK EUR",
            invoice_number="IP-00001368",
            invoice_date="2026-10-09",
            prices=prices,
            rate=4.7,
            vendor="Bonna",
            payment_days=45,
        )
        self.assertEqual(payload["TypeCode"], "DIM")
        self.assertEqual(payload["Series"], "sDIM")
        self.assertEqual(payload["Positions"][0]["VatRate"]["Code"], "23%")
        self.assertEqual(payload["Positions"][0]["PriceValue"], 100.0)
        self.assertAlmostEqual(payload["Positions"][0]["Value"], 517.0)
        self.assertAlmostEqual(payload["Positions"][0]["Duty"], 408.43)
        self.assertEqual(payload["MaturityDate"], "2026-11-23")


class ApiVersionTests(unittest.TestCase):
    def test_default_and_override_from_environment(self):
        import os
        from unittest.mock import patch

        import symfonia_api

        with patch.object(symfonia_api, "ENV_FILE", Path(tempfile.gettempdir()) / "brak-symfonia.env"):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SYMFONIA_WEBAPI_VERSION", None)
                self.assertEqual(symfonia_api.api_version(), "v2026.3")
            with patch.dict(os.environ, {"SYMFONIA_WEBAPI_VERSION": "/v2026.4/"}):
                self.assertEqual(symfonia_api.api_version(), "v2026.4")

    def test_check_codes_uses_configured_version(self):
        import os
        from unittest.mock import patch

        seen = []

        class Recorder(FakeSession):
            def call(self, method, path, body=None):
                seen.append(path)
                return super().call(method, path, body)

        with patch.dict(os.environ, {"SYMFONIA_WEBAPI_VERSION": "v2026.4"}):
            check_codes(Recorder({"LE-1"}), ["LE-1"])
        self.assertTrue(seen and all(path.startswith("/api/v2026.4/") for path in seen))
