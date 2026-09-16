import tkinter as tk
from gui.app import InvoiceParserApp

def main():
    root = tk.Tk()
    app = InvoiceParserApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
