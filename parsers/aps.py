from parsers.base import InvoiceParserStrategy

class APSInvoiceParser(InvoiceParserStrategy):
    keywords = ["assheuer", "sundern", "aps-germany"]
    vendor_name = "APS"

    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        products_matrix = []
        pdf_total_amount = 0.0
        look_for_total = False

        for line in page_text_list:
            clean_line = line.strip()

            if look_for_total:
                parts = clean_line.split(" ")
                if parts:
                    try:
                        raw_amount = parts[-1].replace(".", "").replace(",", ".")
                        pdf_total_amount = float(raw_amount)
                    except ValueError:
                        pass
                look_for_total = False

            if "amount" in clean_line.lower() and "final amount" in clean_line.lower():
                look_for_total = True

            if len(clean_line) >= 13 and clean_line[0:13].isdigit():
                raw_row_data = clean_line.split(" ")
                row_data = []

                if len(raw_row_data) < 5:
                    continue

                row_data.append(raw_row_data[0])  # EAN
                row_data.append("AP-" + raw_row_data[1].zfill(5))  # Product_code
                row_data.append(int(raw_row_data[2].replace(" ", "")))  # Qty_shipped

                if "%" in raw_row_data[-2]:
                    row_data.append(" ".join(raw_row_data[3:-3]))  # Description
                    row_data.append(float(raw_row_data[-3].replace(".", "").replace(",", ".")))  # Price
                    row_data.append(float(raw_row_data[-2].removesuffix("%").replace(",", ".")))  # Discount
                    row_data.append(float(raw_row_data[-1].replace(".", "").replace(",", ".")))  # Value
                else:
                    row_data.append(" ".join(raw_row_data[3:-2]))  # Description
                    row_data.append(float(raw_row_data[-2].replace(".", "").replace(",", ".")))  # Price
                    row_data.append(0.0)  # Discount
                    row_data.append(float(raw_row_data[-1].replace(".", "").replace(",", ".")))  # Value

                products_matrix.append(row_data)

        return products_matrix, pdf_total_amount