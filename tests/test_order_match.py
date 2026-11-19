import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from order_match import OwnOrderSnapshot, clipboard_text, match_invoice_to_orders
from symfonia_api import SymfoniaError
from symfonia_orders import load_purchase_lines, read_open_orders


class OrderMatchTests(unittest.TestCase):
    def test_backorder_from_another_order_is_named(self):
        report = match_invoice_to_orders(
            [("CO-6038/100", 15), ("CO-1147/100", 5), ("CO-3863/022", 50), ("CO-3863/022", 50)],
            [
                OwnOrderSnapshot("0006/26/ZWW", "2026-11-09", {"CO-6038/100": 15, "CO-1147/100": 5}),
                OwnOrderSnapshot("0002/26/ZWW", "2026-09-01", {"CO-3863/022": 80}),
            ],
        )
        self.assertEqual(report.proposed_number, "0006/26/ZWW")
        self.assertEqual(report.headline, "Przed powiązaniem dopisz do 0006/26/ZWW 1 pozycję")
        self.assertEqual(len(report.missing), 1)
        missing = report.missing[0]
        self.assertEqual(missing.code, "CO-3863/022")
        self.assertAlmostEqual(missing.quantity, 100)
        self.assertEqual([(item.number, item.quantity) for item in missing.elsewhere], [("0002/26/ZWW", 80)])

    def test_two_invoice_lines_of_one_code_count_once(self):
        report = match_invoice_to_orders(
            [("CO-3863/022", 50), ("CO-3863/022", 50)],
            [OwnOrderSnapshot("0006/26/ZWW", "2026-11-09", {"CO-3863/022": 100})],
        )
        self.assertEqual(report.missing, ())
        self.assertEqual(report.surplus, ())
        self.assertEqual(report.headline, "Faktura da się powiązać z 0006/26/ZWW bez zmian")

    def test_invoice_quantity_above_the_order_is_a_surplus(self):
        report = match_invoice_to_orders(
            [("BN-GRM30DZ", 200), ("BN-GRM30DZ", 52), ("BN-OTHER", 1)],
            [
                OwnOrderSnapshot("0003/26/ZWW", "2026-11-01", {"BN-GRM30DZ": 48, "BN-OTHER": 1}),
                OwnOrderSnapshot("0001/26/ZWW", "2026-08-01", {"BN-GRM30DZ": 30}),
                OwnOrderSnapshot("0008/25/ZMW", "2025-12-01", {"BN-GRM30DZ": 12}),
                OwnOrderSnapshot("0009/26/ZWW", "2026-11-10", {"BN-GRM30DZ": 90}),
            ],
        )
        self.assertEqual(report.proposed_number, "0003/26/ZWW")
        self.assertEqual(report.missing, ())
        self.assertEqual(report.headline, "Przed powiązaniem podnieś ilość w 0003/26/ZWW w 1 pozycji")
        self.assertEqual(len(report.surplus), 1)
        item = report.surplus[0]
        self.assertEqual(item.code, "BN-GRM30DZ")
        self.assertAlmostEqual(item.order_quantity, 48)
        self.assertAlmostEqual(item.invoice_quantity, 252)
        self.assertEqual(
            [(waiting.number, waiting.quantity) for waiting in item.elsewhere],
            [("0008/25/ZMW", 12), ("0001/26/ZWW", 30)],
        )
        text = clipboard_text(report, "0013/26/DIM")
        self.assertIn("Dokument 0013/26/DIM.", text)
        self.assertIn("podnieś ilość w 0003/26/ZWW z 48 do 252", text)
        self.assertIn("0008/25/ZMW (zamówiono 12 szt.)", text)
        self.assertNotIn("0009/26/ZWW", text)

    def test_excel_export_keeps_the_headline_and_the_surplus(self):
        report = match_invoice_to_orders(
            [("BN-GRM30DZ", 252)],
            [OwnOrderSnapshot("0003/26/ZWW", "2026-11-01", {"BN-GRM30DZ": 48})],
        )
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "raport.xlsx"
        from gui.order_report import _write_excel

        _write_excel(str(path), report, "0013/26/DIM")
        import pandas as pd

        frame = pd.read_excel(path, sheet_name="Powiązanie", header=None)
        self.assertEqual(frame.iloc[0, 0], "Przed powiązaniem podnieś ilość w 0003/26/ZWW w 1 pozycji")
        self.assertIn("0013/26/DIM", str(frame.iloc[1, 0]))
        self.assertIn("ilość zamówiona", str(frame.iloc[2, 0]))
        table = pd.read_excel(path, sheet_name="Powiązanie", header=3)
        self.assertEqual(table.iloc[0]["Kod"], "BN-GRM30DZ")
        self.assertEqual(table.iloc[0]["Polecenie"], "podnieś ilość w 0003/26/ZWW z 48 do 252")

    def test_matching_invoice_needs_no_change(self):
        report = match_invoice_to_orders(
            [("CO-A", 1), ("CO-B", 2)],
            [OwnOrderSnapshot("0006/26/ZWW", "2026-11-09", {"CO-A": 1, "CO-B": 2, "CO-C": 9})],
        )
        self.assertEqual(report.headline, "Faktura da się powiązać z 0006/26/ZWW bez zmian")
        self.assertEqual(report.missing, ())
        self.assertEqual(report.only_on_order, (("CO-C", 9),))

    def test_no_shared_codes_proposes_nothing(self):
        report = match_invoice_to_orders(
            [("CO-A", 4)],
            [OwnOrderSnapshot("0006/26/ZWW", "2026-11-09", {"CO-B": 1})],
        )
        self.assertIsNone(report.proposed_number)
        self.assertIn("nie ma wspólnych", report.headline)
        self.assertEqual(report.missing, ())
        self.assertEqual(report.only_on_order, ())


class OwnOrderReadTests(unittest.TestCase):
    def test_open_orders_skip_buffer_and_realized_and_sum_absolute_qty(self):
        class Session:
            def call(self, method, path, body=None):
                if "/OwnOrders/Filter/" in path:
                    self.filter_path = path
                    return 200, json.dumps([
                        {
                            "Id": 1,
                            "DocumentNumber": "0006/26/ZWW",
                            "TypeCode": "ZWW",
                            "Active": True,
                            "Canceled": 0,
                            "Buffer": False,
                            "IssueDate": "2026-11-09T00:00:00",
                        },
                        {
                            "Id": 2,
                            "DocumentNumber": "0001/26/ZWW",
                            "TypeCode": "ZWW",
                            "Active": True,
                            "Canceled": 0,
                            "Buffer": True,
                            "IssueDate": "2026-01-01T00:00:00",
                        },
                        {
                            "Id": 3,
                            "DocumentNumber": "0009/26/ZWW",
                            "TypeCode": "ZWW",
                            "Active": True,
                            "Canceled": 0,
                            "Buffer": False,
                            "IssueDate": "2026-10-01T00:00:00",
                        },
                        {
                            "Id": 4,
                            "DocumentNumber": "0004/26/ZMW",
                            "TypeCode": "ZMW",
                            "Active": True,
                            "Canceled": 0,
                            "Buffer": False,
                            "IssueDate": "2026-06-01T00:00:00",
                        },
                    ])
                if path.endswith("/OwnOrders/1"):
                    return 200, json.dumps({"Positions": [
                        {"ProductCode": "CO-A", "Quantity": -2},
                        {"ProductCode": "CO-A", "Quantity": -3},
                    ]})
                if path.endswith("/Status/1"):
                    return 200, json.dumps({
                        "DocumentStatus": 8,
                        "DocumentStatusText": "REALIZACJA CZĘŚCIOWA",
                    })
                if path.endswith("/OwnOrders/3"):
                    return 200, json.dumps({"Positions": [{"ProductCode": "CO-B", "Quantity": 4}]})
                if path.endswith("/Status/3"):
                    return 200, json.dumps({"DocumentStatusText": "ZREALIZOWANE"})
                if path.endswith("/OwnOrders/4"):
                    return 200, json.dumps({"Positions": [{"ProductCode": "CO-D", "Quantity": 7}]})
                if path.endswith("/Status/4"):
                    return 200, json.dumps({"DocumentStatusText": "REALIZACJA CZĘŚCIOWA"})
                raise AssertionError(path)

        session = Session()
        orders = read_open_orders(session, "MESA EUROPA LDA", today=date(2026, 11, 17))
        self.assertIn("/OwnOrders/Filter/MESA%20EUROPA%20LDA/2025-11-17/2026-11-17", session.filter_path)
        self.assertEqual([(item.number, item.quantities) for item in orders], [
            ("0006/26/ZWW", {"CO-A": 5.0}),
            ("0004/26/ZMW", {"CO-D": 7.0}),
        ])

    def test_purchase_in_buffer_is_read_when_issued_copy_is_missing(self):
        class Session:
            def call(self, method, path, body=None):
                if path.endswith("/Purchases/FromBuffer/0293%2F26%2FWNT"):
                    raise SymfoniaError("missing", status=404)
                if path.endswith("/Purchases/Issued/0293%2F26%2FWNT"):
                    return 200, json.dumps({
                        "SellerId": 88,
                        "Positions": [
                            {"ProductCode": "CO-3863/022", "Quantity": 50},
                            {"ProductCode": "CO-3863/022", "Quantity": 50},
                        ],
                    })
                if path.endswith("/Contractors/88"):
                    return 200, json.dumps({"Code": "CONTACTO"})
                raise SymfoniaError("missing", status=404)

        code, lines = load_purchase_lines(Session(), "0293/26/WNT")
        self.assertEqual(code, "CONTACTO")
        self.assertEqual(lines, [("CO-3863/022", 50), ("CO-3863/022", 50)])


if __name__ == "__main__":
    unittest.main()


class HeadlineAndCacheTests(unittest.TestCase):
    def test_surplus_only_says_raise_quantity(self):
        report = match_invoice_to_orders(
            [("BN-A", 84), ("BN-B", 252)],
            [OwnOrderSnapshot("0003/26/ZWW", "2026-10-29", {"BN-A": 24, "BN-B": 48})],
        )
        self.assertEqual(report.headline, "Przed powiązaniem podnieś ilość w 0003/26/ZWW w 2 pozycjach")

    def test_missing_and_surplus_together(self):
        report = match_invoice_to_orders(
            [("BN-A", 84), ("BN-NEW", 1)],
            [OwnOrderSnapshot("0003/26/ZWW", "2026-10-29", {"BN-A": 24})],
        )
        self.assertEqual(
            report.headline, "Przed powiązaniem dopisz do 0003/26/ZWW 1 pozycję i podnieś ilość w 1 pozycji"
        )

    def test_older_orders_show_ordered_quantity_with_a_note(self):
        from order_match import OLDER_ORDERS_NOTE, clipboard_text

        report = match_invoice_to_orders(
            [("CO-1", 10), ("CO-2", 1)],
            [
                OwnOrderSnapshot("0006/26/ZWW", "2026-11-09", {"CO-2": 1}),
                OwnOrderSnapshot("0002/26/ZWW", "2026-09-01", {"CO-1": 80}),
            ],
        )
        text = clipboard_text(report)
        self.assertIn("0002/26/ZWW (zamówiono 80 szt.)", text)
        self.assertIn(OLDER_ORDERS_NOTE, text)

    def test_finished_orders_are_not_read_twice_open_ones_are(self):
        import json

        import symfonia_orders

        symfonia_orders._FINISHED.clear()
        self.addCleanup(symfonia_orders._FINISHED.clear)
        calls = []

        class Session:
            def call(self, method, path, body=None):
                calls.append(path)
                if "/Filter/" in path:
                    return 200, json.dumps([
                        {"Id": 1, "TypeCode": "ZWW", "DocumentNumber": "1/26/ZWW", "IssueDate": "2026-10-01"},
                        {"Id": 2, "TypeCode": "ZWW", "DocumentNumber": "2/26/ZWW", "IssueDate": "2026-11-01"},
                    ])
                if path.endswith("/OwnOrders/1"):
                    return 200, json.dumps({"Settled": True, "Positions": []})
                if "/Status/" in path:
                    return 200, json.dumps({"DocumentStatusText": "Niezrealizowane"})
                return 200, json.dumps({"Positions": [{"ProductCode": "CO-1", "Quantity": -5}]})

        first = symfonia_orders.read_open_orders(Session(), "CONTACTO")
        reads_first = len(calls)
        calls.clear()
        second = symfonia_orders.read_open_orders(Session(), "CONTACTO")
        self.assertEqual([o.number for o in first], ["2/26/ZWW"])
        self.assertEqual([o.number for o in second], ["2/26/ZWW"])
        self.assertFalse(any(path.endswith("/OwnOrders/1") for path in calls))
        self.assertLess(len(calls), reads_first)
