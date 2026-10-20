"""Generate reproducible, non-identical 2024/2025 sample sales history."""
from pathlib import Path
import random
from openpyxl import Workbook

random.seed(20261007)
HEADERS = ["Warehouse ID", "Warehouse Name", "SKU", "Product Name", "Category", "Month", "Year", "Units Shipped", "Unit Cost", "Stock On Hand", "Reorder Level", "Season"]
WAREHOUSES = [("WH-PP", "Phnom Penh Central"), ("WH-SR", "Siem Reap Hub"), ("WH-BB", "Battambang Depot")]
PRODUCTS = [("SKU-1001", "Rice Cooker", "Appliances", 68, 45), ("SKU-1002", "Electric Kettle", "Appliances", 72, 28), ("SKU-1003", "Bath Towel", "Home Goods", 86, 12), ("SKU-1004", "Storage Box", "Home Goods", 61, 9), ("SKU-1005", "Running Shoes", "Sports", 54, 38), ("SKU-1006", "Yoga Mat", "Sports", 76, 19), ("SKU-1007", "Wireless Mouse", "Electronics", 83, 17), ("SKU-1008", "LED Desk Lamp", "Electronics", 64, 24)]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
SEASONAL = [0.86, 0.89, 0.94, 0.98, 1.04, 1.10, 1.08, 1.05, 1.01, 1.16, 1.28, 1.34]
def season(month): return "Rainy" if 5 <= month <= 9 else "Dry"
def main():
    rows = []
    for warehouse_index, (warehouse_id, warehouse_name) in enumerate(WAREHOUSES):
        for sku, name, category, base, cost in PRODUCTS:
            growth = random.uniform(1.00, 1.12); prior = {}
            for year in (2024, 2025):
                for month in range(1, 13):
                    if year == 2024: units = round(base * SEASONAL[month - 1] * (0.92 + warehouse_index * .07) * random.uniform(.92, 1.08))
                    else: units = round(prior[month] * growth * random.uniform(.92, 1.08))
                    prior[month] = units
                    reorder = round(base * 1.30)
                    stock = max(10, round(units * random.uniform(.75, 1.45)))
                    rows.append([warehouse_id, warehouse_name, sku, name, category, MONTHS[month - 1], year, units, cost, stock, reorder, season(month)])
    workbook = Workbook(); sheet = workbook.active; sheet.title = "Warehouse History"; sheet.append(HEADERS)
    for row in rows: sheet.append(row)
    sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]: cell.font = __import__("openpyxl").styles.Font(bold=True, color="FFFFFF"); cell.fill = __import__("openpyxl").styles.PatternFill("solid", fgColor="102A43")
    root = Path(__file__).resolve().parents[1]
    for output in (root / "fixtures" / "stockforecast_sample.xlsx", root / "static" / "fixtures" / "stockforecast_sample.xlsx"):
        output.parent.mkdir(parents=True, exist_ok=True); workbook.save(output)
if __name__ == "__main__": main()
