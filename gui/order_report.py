import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from order_match import EXPORT_COLUMNS, MatchReport, clipboard_text, export_rows


class OrderLinkWindow(tk.Toplevel):
    """What to add to an own order before Symfonia will link the invoice."""

    def __init__(self, parent, report: MatchReport, document_number: str = ""):
        super().__init__(parent)
        self.title("Powiązanie z zamówieniem")
        self.geometry("860x480")
        self.transient(parent)
        self.report = report
        self.document_number = document_number

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=report.headline, wraplength=820, font=("TkDefaultFont", 10, "bold")).pack(
            anchor=tk.W, pady=(0, 4)
        )
        detail = _detail_line(report, document_number)
        if detail:
            ttk.Label(frame, text=detail, wraplength=820).pack(anchor=tk.W, pady=(0, 8))

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical")
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree = ttk.Treeview(
            table_frame,
            columns=("kind", "code", "qty", "note"),
            show="headings",
            yscrollcommand=scroll.set,
        )
        tree.heading("kind", text="Rodzaj")
        tree.heading("code", text="Kod")
        tree.heading("qty", text="Ilość")
        tree.heading("note", text="Inne zamówienia")
        tree.column("kind", width=160, anchor=tk.W)
        tree.column("code", width=160, anchor=tk.W)
        tree.column("qty", width=80, anchor=tk.E)
        tree.column("note", width=400, anchor=tk.W)
        for item in report.missing:
            tree.insert(
                "",
                tk.END,
                values=("Dopisać do zamówienia", item.code, _qty(item.quantity), _elsewhere(item.elsewhere)),
            )
        for item in report.surplus:
            tree.insert(
                "",
                tk.END,
                values=(
                    "Nadwyżka ilości",
                    item.code,
                    _qty(item.invoice_quantity),
                    _surplus_note(report.proposed_number or "", item),
                ),
            )
        for code, qty in report.only_on_order:
            tree.insert(
                "",
                tk.END,
                values=("Tylko na zamówieniu", code, _qty(qty), "nie blokuje powiązania"),
            )
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=tree.yview)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="Kopiuj", command=self.copy_report).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Eksportuj do Excela", command=self.export_excel).pack(side=tk.LEFT, padx=8)
        self.copy_status = ttk.Label(buttons, text="")
        self.copy_status.pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="Zamknij", command=self.destroy).pack(side=tk.RIGHT)
        self.focus_set()

    def copy_report(self):
        text = clipboard_text(self.report, self.document_number)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.copy_status.config(text="Skopiowano do schowka.")

    def export_excel(self):
        suggested = _excel_name(self.document_number or self.report.proposed_number or "powiazanie")
        file_path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".xlsx",
            filetypes=[("Pliki Excela", "*.xlsx")],
            title="Zapisz raport powiązania",
            initialfile=suggested,
        )
        if not file_path:
            return
        try:
            _write_excel(file_path, self.report, self.document_number)
        except Exception as exc:
            messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać pliku:\n{exc}", parent=self)
            return
        self.copy_status.config(text="Zapisano plik Excel.")


def _detail_line(report: MatchReport, document_number: str) -> str:
    parts = []
    if document_number:
        parts.append(f"Dokument {document_number}.")
    if report.proposed_number:
        when = _pl_date(report.proposed_date)
        dated = f" z {when}" if when else ""
        parts.append(f"Proponowane zamówienie: {report.proposed_number}{dated}.")
    return " ".join(parts)


def _surplus_note(order_number: str, item) -> str:
    change = (
        f"podnieś ilość w {order_number} z {_qty(item.order_quantity)} do {_qty(item.invoice_quantity)}"
    )
    return f"{change}; {_elsewhere(item.elsewhere)}"


def _elsewhere(waiting) -> str:
    if not waiting:
        return "nie ma na starszych ZWW/ZMW"
    return "; ".join(f"{item.number} ({_qty(item.quantity)} szt.)" for item in waiting)


def _qty(value: float) -> str:
    if abs(value - round(value)) < 0.0001:
        return str(int(round(value)))
    return f"{value:.2f}".replace(".", ",")


def _write_excel(path: str, report: MatchReport, document_number: str) -> None:
    frame = pd.DataFrame(export_rows(report), columns=list(EXPORT_COLUMNS))
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Powiązanie", startrow=3)
        sheet = writer.sheets["Powiązanie"]
        sheet["A1"] = report.headline
        sheet["A2"] = _detail_line(report, document_number)


def _excel_name(number: str) -> str:
    safe = re.sub(r"[^\w.-]+", "-", number.strip()) or "powiazanie"
    return f"powiazanie_{safe}.xlsx"


def _pl_date(iso: str) -> str:
    text = (iso or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text.split("-")
        return f"{day}.{month}.{year}"
    return text
