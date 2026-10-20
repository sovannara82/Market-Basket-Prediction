from dataclasses import dataclass
import pandas as pd
from django.db import transaction
from .models import StockLedger
from .forecasting import invalidate_model_cache

SOURCE_COLUMNS = ["Warehouse ID", "Warehouse Name", "SKU", "Product Name", "Category", "Month", "Year", "Units Shipped", "Unit Cost", "Stock On Hand", "Reorder Level", "Season"]
FIELD_NAMES = {"Warehouse ID":"warehouse_id", "Warehouse Name":"warehouse_name", "SKU":"sku", "Product Name":"product_name", "Category":"category", "Month":"month", "Year":"year", "Units Shipped":"units_shipped", "Unit Cost":"unit_cost", "Stock On Hand":"stock_on_hand", "Reorder Level":"reorder_level", "Season":"season"}
MONTHS = {name: number for number, name in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}

@dataclass
class IntakeResult:
    records: pd.DataFrame
    report: dict
    preview: list

def _month(value):
    if isinstance(value, str):
        value = MONTHS.get(value.strip().title(), value)
    return pd.to_numeric(value, errors="coerce")

def prepare_workbook(uploaded):
    try:
        raw = pd.read_excel(uploaded, engine="openpyxl")
    except Exception as exc:
        raise ValueError("This workbook could not be read as an Excel file.") from exc
    raw.columns = [str(column).strip() for column in raw.columns]
    absent = [col for col in SOURCE_COLUMNS if col not in raw.columns]
    if absent:
        raise ValueError("Missing required columns: " + ", ".join(absent))
    before = len(raw)
    data = raw[SOURCE_COLUMNS].replace(r"^\s*$", pd.NA, regex=True).copy()
    blank_rows = int(data.isna().all(axis=1).sum())
    duplicate_rows = int(data.duplicated().sum())
    data = data.dropna(how="all").drop_duplicates()
    for col in ["Warehouse ID", "Warehouse Name", "SKU", "Product Name", "Category", "Season"]:
        data[col] = data[col].fillna("").astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    data["Warehouse ID"] = data["Warehouse ID"].str.upper()
    data["SKU"] = data["SKU"].str.upper()
    data["Warehouse Name"] = data["Warehouse Name"].str.title()
    # Product names such as TV and USB must retain their supplied capitalization.
    data["Category"] = data["Category"].str.title()
    data["Season"] = data["Season"].replace("", "Unspecified").str.title()
    data["Month"] = data["Month"].map(_month)
    data["Year"] = pd.to_numeric(data["Year"], errors="coerce")
    data["Units Shipped"] = pd.to_numeric(data["Units Shipped"], errors="coerce")
    rows_missing_units = int(data["Units Shipped"].isna().sum())
    data = data.dropna(subset=["Units Shipped"])
    same_pair_values_filled = 0
    global_values_filled = 0
    for col in ["Units Shipped", "Unit Cost", "Stock On Hand", "Reorder Level"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")
        if col == "Units Shipped":
            data[col] = data[col].clip(lower=0)
            continue
        data[col] = data[col].astype(float)
        pair_median = data.groupby(["Warehouse ID", "SKU"])[col].transform("median")
        missing = data[col].isna()
        from_pair = missing & pair_median.notna()
        same_pair_values_filled += int(from_pair.sum())
        if from_pair.any():
            data.loc[from_pair, col] = pair_median[from_pair]
        missing = data[col].isna()
        global_median = data[col].median()
        global_values_filled += int(missing.sum())
        if missing.any():
            data.loc[missing, col] = 0 if pd.isna(global_median) else global_median
        data[col] = data[col].clip(lower=0)
    valid = data["Month"].between(1, 12) & data["Year"].between(2000, 2100)
    sku_ok = data["SKU"].str.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,49}$", na=False)
    essential = (data["Warehouse ID"] != "") & (data["Warehouse Name"] != "") & (data["Product Name"] != "")
    rejected = int((~(valid & sku_ok & essential)).sum())
    data = data[valid & sku_ok & essential].copy()
    data["Month"] = data["Month"].astype(int); data["Year"] = data["Year"].astype(int)
    for col in ["Units Shipped", "Stock On Hand", "Reorder Level"]: data[col] = data[col].round().astype(int)
    period_duplicates = int(data.duplicated(subset=["SKU", "Month", "Year", "Warehouse ID"]).sum())
    data = data.drop_duplicates(subset=["SKU", "Month", "Year", "Warehouse ID"], keep="last").rename(columns=FIELD_NAMES)
    report = {"rows_before": before, "rows_after": len(data), "duplicates_removed": duplicate_rows + period_duplicates, "empty_rows_removed": blank_rows, "rows_missing_units": rows_missing_units, "malformed_rows_rejected": rejected, "same_pair_values_filled": same_pair_values_filled, "global_values_filled": global_values_filled, "missing_values_fixed": same_pair_values_filled + global_values_filled, "success_rate": round(100 * len(data) / before, 1) if before else 0}
    preview = data.head(10).where(pd.notna(data), "").to_dict("records")
    return IntakeResult(data, report, preview)

@transaction.atomic
def save_ledger(data):
    keys = list(data[["sku", "month", "year", "warehouse_id"]].itertuples(index=False, name=None))
    existing = set(StockLedger.objects.filter(
        sku__in=data["sku"].unique(), warehouse_id__in=data["warehouse_id"].unique()
    ).values_list("sku", "month", "year", "warehouse_id"))
    added = sum(key not in existing for key in keys); updated = len(keys) - added
    fields = [field.name for field in StockLedger._meta.fields if field.name not in {"id", "sku", "month", "year", "warehouse_id", "uploaded_at"}]
    objects = [StockLedger(**entry) for entry in data.to_dict("records")]
    StockLedger.objects.bulk_create(objects, batch_size=500, update_conflicts=True,
        unique_fields=["sku", "month", "year", "warehouse_id"], update_fields=fields)
    invalidate_model_cache()
    return added, updated
