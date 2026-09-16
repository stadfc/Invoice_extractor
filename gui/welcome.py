import tkinter as tk
from tkinter import ttk


class WelcomeWindow(tk.Toplevel):
    """Startup dialog listing vendor parsers registered in the factory."""

    def __init__(self, parent, vendor_names: list[str]):
        super().__init__(parent)
        self.title("Witamy")
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Uniwersalny ekstraktor produktów z faktur",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)

        ttk.Label(
            frame,
            text="Dostawca jest rozpoznawany automatycznie. Dostępne parsery:",
            wraplength=420,
        ).pack(anchor=tk.W, pady=(8, 6))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        vendors = ttk.Treeview(
            list_frame,
            columns=("vendor",),
            show="headings",
            height=max(6, len(vendor_names)),
            selectmode="none",
        )
        vendors.heading("vendor", text="Parser / dostawca")
        vendors.column("vendor", width=400, anchor=tk.W)
        for name in vendor_names:
            vendors.insert("", tk.END, values=(name,))
        vendors.pack(fill=tk.BOTH, expand=True)

        ttk.Button(frame, text="Dalej", command=self.destroy).pack(pady=(12, 0), anchor=tk.E)

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        self._center_on_parent(parent)
        self.grab_set()
        self.focus_set()

    def _center_on_parent(self, parent):
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + max((pw - width) // 2, 0)
        y = py + max((ph - height) // 2, 0)
        self.geometry(f"+{x}+{y}")
