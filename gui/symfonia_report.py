import tkinter as tk
from tkinter import ttk


class CodeReportWindow(tk.Toplevel):
    """Which invoice codes already have a Symfonia product card."""

    def __init__(self, parent, title: str, rows: list[tuple[str, str, str]]):
        super().__init__(parent)
        self.title("Kody w Symfonii")
        self.geometry("760x420")
        self.transient(parent)

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

        ttk.Button(frame, text="Zamknij", command=self.destroy).pack(anchor=tk.E, pady=(8, 0))
        self.focus_set()
