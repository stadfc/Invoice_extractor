import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
from dataclasses import replace
from pathlib import Path
import pandas as pd

from parsers.factory import InvoiceParserFactory
from pipeline import format_for_import, format_money, parse_invoices
from gui.welcome import WelcomeWindow


class InvoiceParserApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Uniwersalny Ekstraktor Produktów z Faktur")
        self.root.geometry("900x600")

        self.parser_factory = InvoiceParserFactory()
        self.df = pd.DataFrame()
        self.pdf_total_amount = 0.0
        self.transport_cost = 0.0
        self.header_discount = 0.0  # Osobne pole na rabat nagłówkowy
        self.is_external_transport = False
        self.current_vendor = ""
        self.current_invoice_number = ""
        self.current_currency = "EUR"
        self.documents = []
        self.document_index = 0

        self.is_import_format_active = False

        self.columns = ["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"]
        self.create_widgets()
        self.root.after(150, self.show_welcome)

    def create_widgets(self):
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(side=tk.TOP, fill=tk.X)

        button_row = ttk.Frame(top_frame)
        button_row.pack(side=tk.TOP, fill=tk.X)

        self.btn_open = ttk.Button(button_row, text="Wybierz plik PDF", command=self.process_pdf)
        self.btn_open.pack(side=tk.LEFT, padx=5)

        self.btn_save = ttk.Button(button_row, text="Zapisz do Excela", command=self.save_to_excel, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT, padx=5)

        self.btn_remove_zeros = ttk.Button(button_row, text="Usuń wiersze zerowe", command=self.remove_zeros,
                                           state=tk.DISABLED)
        self.btn_remove_zeros.pack(side=tk.LEFT, padx=5)

        self.btn_import_format = ttk.Button(button_row, text="Formatuj do importu", command=self.import_format,
                                            state=tk.DISABLED)
        self.btn_import_format.pack(side=tk.LEFT, padx=5)

        self.btn_vendors = ttk.Button(button_row, text="Dostawcy", command=self.show_welcome)
        self.btn_vendors.pack(side=tk.LEFT, padx=5)

        ttk.Label(button_row, text="Faktura:").pack(side=tk.LEFT, padx=(12, 4))
        self.invoice_choice = tk.StringVar()
        self.invoice_combo = ttk.Combobox(
            button_row,
            textvariable=self.invoice_choice,
            state="disabled",
            width=18,
        )
        self.invoice_combo.pack(side=tk.LEFT, padx=5)
        self.invoice_combo.bind("<<ComboboxSelected>>", self.on_invoice_selected)

        self.lbl_status = ttk.Label(
            top_frame,
            text="Status: Oczekiwanie na plik PDF...",
            anchor=tk.W,
            wraplength=860,
        )
        self.lbl_status.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(8, 0))

        self.table_frame = ttk.Frame(self.root)
        self.table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.vsb = ttk.Scrollbar(self.table_frame, orient="vertical")
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.hsb = ttk.Scrollbar(self.table_frame, orient="horizontal")
        self.hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self.setup_treeview()

    def setup_treeview(self):
        if hasattr(self, 'tree') and self.tree:
            self.tree.destroy()

        self.tree = ttk.Treeview(self.table_frame, columns=self.columns, show="headings")

        for col in self.columns:
            self.tree.heading(col, text=col)
            if col == "Description":
                self.tree.column(col, width=350, anchor=tk.W)
            else:
                self.tree.column(col, width=130, anchor=tk.CENTER)

        self.tree.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.vsb.configure(command=self.tree.yview)
        self.hsb.configure(command=self.tree.xview)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self.on_double_click)

    def show_welcome(self):
        existing = getattr(self, "_welcome", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        self._welcome = WelcomeWindow(self.root, self.parser_factory.available_vendors())

    def process_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=[("Pliki PDF", "*.pdf")])
        if not file_path:
            return

        self.lbl_status.config(text="Status: Analizowanie formatu pliku...")
        self.root.update_idletasks()

        self.columns = ["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"]
        self.is_import_format_active = False
        self.setup_treeview()
        self.transport_cost = 0.0
        self.header_discount = 0.0
        self.is_external_transport = False

        try:
            documents = parse_invoices(Path(file_path))
            self.documents = documents
            self.document_index = 0
            first = documents[0]
            self.current_vendor = first.vendor
            numbers = [doc.invoice_number or f"Faktura {i + 1}" for i, doc in enumerate(documents)]
            messagebox.showinfo(
                "Rozpoznano format",
                f"Wykryto profil dostawcy: {self.current_vendor}\n"
                f"Liczba faktur w pliku: {len(documents)}\n"
                + "\n".join(numbers),
            )

            self.invoice_combo["values"] = numbers
            self.invoice_combo.set(numbers[0])
            self.invoice_combo.config(state="readonly" if len(documents) > 1 else "disabled")

            if first.transport_cost <= 0.0:
                if self.current_vendor in ["Leone", "Sola Swiss"]:
                    self.prompt_for_transport(force=True)
                    self.documents[0] = replace(
                        first,
                        transport_cost=self.transport_cost,
                        transport_is_external=True,
                    )
                elif self.current_vendor == "Pintinox":
                    if messagebox.askyesno(
                        "Koszt transportu",
                        "Czy do tej faktury Pintinox należy doliczyć zewnętrzny koszt transportu?",
                    ):
                        self.prompt_for_transport(force=False)
                        self.documents[0] = replace(
                            first,
                            transport_cost=self.transport_cost,
                            transport_is_external=self.transport_cost > 0,
                        )

            self._load_document(0)

        except Exception as e:
            messagebox.showerror("Błąd", f"Wystąpił błąd podczas analizy pliku:\n{str(e)}")
            self.lbl_status.config(text="Status: Błąd krytyczny.")

    def on_invoice_selected(self, _event=None):
        if not self.documents:
            return
        selected = self.invoice_combo.current()
        if selected < 0:
            return
        self._load_document(selected)

    def _load_document(self, index: int):
        doc = self.documents[index]
        self.document_index = index
        self.current_vendor = doc.vendor
        self.current_invoice_number = doc.invoice_number
        self.current_currency = doc.currency or "EUR"
        self.pdf_total_amount = doc.pdf_total_amount
        self.transport_cost = doc.transport_cost
        self.is_external_transport = doc.transport_is_external
        self.header_discount = 0.0
        self.is_import_format_active = False
        self.columns = ["EAN", "Product_code", "Qty_shipped", "Description", "Price", "Discount", "Value"]
        self.setup_treeview()
        self.df = doc.rows.copy()
        self.refresh_treeview()
        self.btn_save.config(state=tk.NORMAL)
        self.btn_remove_zeros.config(state=tk.NORMAL)
        self.btn_import_format.config(state=tk.NORMAL)
        self.update_status_with_validation()
        if doc.transport_cost > 0.0 and not doc.transport_is_external:
            self.lbl_status.config(
                text=(
                    f"Status: {doc.invoice_number or doc.vendor} | transport "
                    f"{format_money(doc.transport_cost, self.current_currency)}"
                )
            )

    def prompt_for_transport(self, force=False):
        prompt_title = "Wymagany koszt transportu" if force else "Koszt transportu"
        prompt_msg = (
            f"Podaj kwotę kosztu transportu dla dostawcy {self.current_vendor} "
            f"({self.current_currency}):"
        )

        while True:
            res = simpledialog.askstring(prompt_title, prompt_msg, parent=self.root)
            if res is None:
                if force:
                    messagebox.showwarning("Wymagana wartość", "Dla tego dostawcy koszt transportu jest obowiązkowy!")
                    continue
                else:
                    break
            try:
                self.transport_cost = float(res.replace(",", "."))
                if self.transport_cost < 0:
                    raise ValueError
                self.is_external_transport = True
                break
            except ValueError:
                messagebox.showerror("Błędna wartość", "Wprowadzona kwota musi być liczbą dodatnią lub 0.")
                if not force:
                    break

    def refresh_treeview(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        for _, row in self.df.iterrows():
            values = list(row)

            if self.is_import_format_active:
                values[1] = f"{values[1]}"
                values[2] = f"{values[2]:.4f}"
            else:
                values[4] = f"{values[4]:.4f}"
                values[5] = f"{values[5]:.2f}%"
                values[6] = f"{values[6]:.2f}"

            self.tree.insert("", tk.END, values=values)

    def update_status_with_validation(self):
        if self.df.empty:
            return

        total_goods = self.df["Value"].sum() if not self.is_import_format_active else 0.0

        if self.is_import_format_active:
            calculated_sum = (self.df["Ilość"] * self.df["Cena jednostkowa"]).sum()
            sum_to_verify = round(float(calculated_sum), 2)
        else:
            sum_to_verify = round(total_goods + self.transport_cost - self.header_discount, 2)

        # Wyznaczenie kwoty docelowej: (Kwota z faktury PDF) + (Transport Zewnętrzny)
        if self.is_external_transport:
            expected_total = round(self.pdf_total_amount + self.transport_cost, 2)
        else:
            expected_total = round(self.pdf_total_amount, 2)

        diff = round(expected_total - sum_to_verify, 2)

        money = lambda value: format_money(value, self.current_currency)
        status_text = (
            f"Dostawca: {self.current_vendor} | Suma w oknie: {money(sum_to_verify)} "
            f"| Oczekiwane: {money(expected_total)}"
        )

        if diff == 0.00:
            self.lbl_status.config(text=f"Status: OK (Zgodność kwot!) | {status_text}", foreground="green")
        else:
            diff_str = f"+{diff:.2f}" if diff > 0 else f"{diff:.2f}"
            self.lbl_status.config(
                text=f"Status: NIEZGODNOŚĆ ({diff_str} {self.current_currency}) | {status_text}",
                foreground="red",
            )

    def import_format(self):
        """
        Konwertuje dane na 3 kolumny, precyzyjnie uwzględniając rabat nagłówkowy oraz koszt transportu.
        """
        if self.df.empty:
            return

        if self.is_import_format_active:
            messagebox.showinfo("Informacja", "Dane są już w formacie importowym.")
            return

        try:
            result = format_for_import(self.df, self.pdf_total_amount, self.transport_cost)
        except ValueError as exc:
            messagebox.showwarning("Błąd proporcji", str(exc))
            return

        self.header_discount = result.header_discount
        self.is_import_format_active = True
        self.columns = ["Kod", "Ilość", "Cena jednostkowa"]
        self.df = result.df

        self.setup_treeview()
        self.refresh_treeview()
        self.update_status_with_validation()

        money = lambda value: format_money(value, self.current_currency)
        msg = f"Przekonwertowano widok do formatu importu (3 kolumny).\n\n"
        msg += f"• Suma produktów brutto przed zmianami: {money(result.total_net_goods)}\n"
        if result.header_discount > 0:
            msg += f"• Uwzględniono rabat nagłówkowy: -{money(result.header_discount)}\n"
        if result.transport_cost > 0:
            msg += f"• Uwzględniono transport: +{money(result.transport_cost)}\n"
        msg += f"-----------------------------------------\n"
        msg += f"Docelowa wartość dokumentu w ERP: {money(result.target_grand_total)}"

        messagebox.showinfo("Formatowanie ukończone", msg)

    def on_double_click(self, event):
        item_id = self.tree.selection()
        if not item_id:
            return

        item_id = item_id[0]
        column_id = self.tree.identify_column(event.x)
        column_idx = int(column_id.replace("#", "")) - 1

        row_values = self.tree.item(item_id, "values")
        col_name = self.columns[column_idx]
        current_val = row_values[column_idx]

        allowed_cols = ["Ilość", "Cena jednostkowa"] if self.is_import_format_active else ["Qty_shipped", "Price",
                                                                                           "Discount"]
        if col_name not in allowed_cols:
            return

        new_val_str = simpledialog.askstring("Edycja pola", f"Zmień wartość dla {col_name}:", initialvalue=current_val)
        if new_val_str is None:
            return

        try:
            df_idx = self.tree.index(item_id)

            if self.is_import_format_active:
                if col_name == "Ilość":
                    self.df.at[df_idx, "Ilość"] = int(new_val_str)
                elif col_name == "Cena jednostkowa":
                    self.df.at[df_idx, "Cena jednostkowa"] = float(new_val_str.replace(",", "."))
            else:
                if col_name == "Qty_shipped":
                    new_val = int(new_val_str)
                    self.df.at[df_idx, col_name] = new_val
                elif col_name == "Price":
                    new_val = float(new_val_str.replace(",", "."))
                    self.df.at[df_idx, col_name] = new_val
                elif col_name == "Discount":
                    new_val = float(new_val_str.replace("%", "").replace(",", "."))
                    self.df.at[df_idx, col_name] = new_val

                qty = self.df.at[df_idx, "Qty_shipped"]
                price = self.df.at[df_idx, "Price"]
                discount = self.df.at[df_idx, "Discount"]
                self.df.at[df_idx, "Value"] = round(qty * price * (1.0 - discount / 100.0), 2)

            self.refresh_treeview()
            self.update_status_with_validation()

        except ValueError:
            messagebox.showerror("Błąd", "Wprowadzono nieprawidłowy format danych.")

    def remove_zeros(self):
        if self.df.empty:
            return

        initial_len = len(self.df)

        if self.is_import_format_active:
            self.df = self.df[(self.df["Ilość"] > 0) & (self.df["Cena jednostkowa"] > 0)]
        else:
            self.df = self.df[(self.df["Qty_shipped"] > 0) & (self.df["Value"] > 0)]

        removed = initial_len - len(self.df)

        self.refresh_treeview()
        self.update_status_with_validation()
        messagebox.showinfo("Porządki", f"Usunięto {removed} pozycji o zerowej wartości lub ilości.")

    def save_to_excel(self):
        if self.df.empty and not self.documents:
            return

        if len(self.documents) > 1:
            folder = filedialog.askdirectory(title="Wybierz folder na osobne pliki Excel (każda faktura osobno)")
            if not folder:
                return
            saved = []
            try:
                for doc in self.documents:
                    formatted = format_for_import(doc.rows, doc.pdf_total_amount, doc.transport_cost)
                    name = f"{doc.invoice_number or 'faktura'}_import.xlsx"
                    path = Path(folder) / name
                    formatted.df.to_excel(path, index=False)
                    saved.append(name)
            except Exception as e:
                messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać plików:\n{str(e)}")
                return
            messagebox.showinfo("Sukces", "Zapisano osobne faktury:\n" + "\n".join(saved))
            return

        suggested = self.current_invoice_number or "zestawienie"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Pliki Excela", "*.xlsx")],
            title="Zapisz zestawienie",
            initialfile=f"{suggested}_import.xlsx",
        )
        if file_path:
            try:
                self.df.to_excel(file_path, index=False)
                messagebox.showinfo("Sukces", "Dane zostały pomyślnie zapisane do pliku Excel.")
            except Exception as e:
                messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać pliku:\n{str(e)}")