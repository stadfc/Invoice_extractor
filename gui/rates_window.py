import tkinter as tk
from tkinter import messagebox, ttk

from exchange_rates import CURRENCIES, RateError, load_rates, parse_rate, save_rates


class RatesWindow(tk.Toplevel):
    """EUR, USD and GBP in PLN. PLN stays at 1."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Kursy walut")
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frame,
            text="Ile złotych za 1 jednostkę waluty. Kurs jest używany przy zapisie WNT.",
            wraplength=360,
        ).pack(anchor=tk.W, pady=(0, 10))

        self.fields: dict[str, tk.StringVar] = {}
        current = load_rates()
        for code in CURRENCIES:
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=code, width=6).pack(side=tk.LEFT)
            if code == "PLN":
                ttk.Label(row, text="1").pack(side=tk.LEFT)
                continue
            variable = tk.StringVar()
            value = current.get(code)
            if value is not None:
                variable.set(f"{value:.4f}".replace(".", ","))
            entry = ttk.Entry(row, textvariable=variable, width=12)
            entry.pack(side=tk.LEFT)
            self.fields[code] = variable

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Anuluj", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Zapisz", command=self._save).pack(side=tk.RIGHT, padx=(0, 6))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self.grab_set()
        self.focus_set()

    def _save(self):
        parsed = {}
        try:
            for code, variable in self.fields.items():
                parsed[code] = parse_rate(variable.get())
        except RateError as exc:
            messagebox.showerror("Kurs waluty", str(exc), parent=self)
            return
        save_rates(parsed)
        self.destroy()
