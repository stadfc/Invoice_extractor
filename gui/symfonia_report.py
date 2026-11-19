import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd


class CodeReportWindow(tk.Toplevel):
    """Which invoice codes already have a Symfonia product card."""

    def __init__(self, parent, title: str, rows: list[tuple[str, str, str]]):
        super().__init__(parent)
        self.title("Kody w Symfonii")
        self.geometry("760x420")
        self.transient(parent)
        self.rows = rows
        self.summary = title

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=title, wraplength=720).pack(anchor=tk.W, pady=(0, 8))

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical")
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree = ttk.Treeview(
            table_frame,
            columns=("code", "status", "name"),
            show="headings",
            yscrollcommand=scroll.set,
        )
        tree.heading("code", text="Kod")
        tree.heading("status", text="Kartoteka")
        tree.heading("name", text="Nazwa")
        tree.column("code", width=140, anchor=tk.W)
        tree.column("status", width=110, anchor=tk.W)
        tree.column("name", width=460, anchor=tk.W)
        for code, status, name in rows:
            tree.insert("", tk.END, values=(code, status, name))
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
        self.clipboard_clear()
        self.clipboard_append(_code_text(self.summary, self.rows))
        self.update()
        self.copy_status.config(text="Skopiowano do schowka.")

    def export_excel(self):
        file_path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".xlsx",
            filetypes=[("Pliki Excela", "*.xlsx")],
            title="Zapisz wynik sprawdzenia kodów",
            initialfile="kody_symfonia.xlsx",
        )
        if not file_path:
            return
        try:
            frame = pd.DataFrame(self.rows, columns=["Kod", "Kartoteka", "Nazwa"])
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                frame.to_excel(writer, index=False, sheet_name="Kody", startrow=2)
                writer.sheets["Kody"]["A1"] = self.summary
        except Exception as exc:
            messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać pliku:\n{exc}", parent=self)
            return
        self.copy_status.config(text="Zapisano plik Excel.")


def _code_text(summary: str, rows: list[tuple[str, str, str]]) -> str:
    lines = [summary, "", "Kod\tKartoteka\tNazwa"]
    for code, status, name in rows:
        lines.append(f"{code}\t{status}\t{name}")
    return "\n".join(lines)
