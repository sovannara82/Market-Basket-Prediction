"""Chronological Linear Regression forecasting and inventory recommendations."""
import math

import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from .models import StockLedger, TrainingRun

Z = 1.28
MIN_MODEL_ROWS = 13
MONTH_FEATURES = [f"month_{month}" for month in range(2, 13)]
MODEL_FEATURES = ["last_year_same_month", "has_last_year", "previous_sales", "stock_on_hand"]
_MODEL_CACHE = _CACHE_METRICS = None


def invalidate_model_cache():
    """Forget fitted state after an import changes historical data."""
    global _MODEL_CACHE, _CACHE_METRICS
    _MODEL_CACHE = _CACHE_METRICS = None


def sales_history_frame(queryset=None):
    """Load persisted history with a continuous numeric calendar period."""
    records = (queryset or StockLedger.objects.all()).values(
        "id", "warehouse_id", "warehouse_name", "sku", "product_name", "category",
        "month", "year", "units_shipped", "stock_on_hand", "reorder_level", "season",
    )
    frame = pd.DataFrame(list(records))
    if not frame.empty:
        frame["period"] = frame.year.astype(int) * 12 + frame.month.astype(int) - 1
    return frame


def _month_feature_values(target_month):
    return {f"month_{month}": int(target_month == month) for month in range(2, 13)}


def build_feature_rows(frame):
    """Build consecutive origin-month ``t`` rows that predict sales at ``t + 1``."""
    columns = [
        "warehouse_id", "sku", "origin_period", "target_period", "target_month",
        "previous_sales", "stock_on_hand", "last_year_actual", "last_year_same_month",
        "has_last_year", "target_sales", *MONTH_FEATURES,
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    data = frame.copy().sort_values(["warehouse_id", "sku", "period"])
    for column in ("units_shipped", "stock_on_hand"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    lookup = data.set_index(["warehouse_id", "sku", "period"])
    rows = []
    for _, origin in data.iterrows():
        target_period = int(origin.period) + 1
        key = (origin.warehouse_id, origin.sku, target_period)
        if key not in lookup.index:
            continue
        target = lookup.loc[key]
        target_month = (target_period % 12) + 1
        last_year_key = (origin.warehouse_id, origin.sku, target_period - 12)
        last_year_actual = lookup.loc[last_year_key, "units_shipped"] if last_year_key in lookup.index else float("nan")
        has_last_year = int(pd.notna(last_year_actual))
        row = {
            "warehouse_id": origin.warehouse_id, "sku": origin.sku,
            "origin_period": int(origin.period), "target_period": target_period,
            "target_month": target_month, "previous_sales": float(origin.units_shipped),
            "stock_on_hand": float(origin.stock_on_hand), "last_year_actual": last_year_actual,
            "last_year_same_month": float(last_year_actual) if has_last_year else float(origin.units_shipped),
            "has_last_year": has_last_year, "target_sales": float(target.units_shipped),
        }
        row.update(_month_feature_values(target_month))
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def chronological_split(rows):
    """Hold out the newest three origin months without shuffling observations."""
    test_periods = sorted(rows.origin_period.unique())[-3:]
    return rows[~rows.origin_period.isin(test_periods)], rows[rows.origin_period.isin(test_periods)]


def _metrics(actual, predicted):
    mse = float(mean_squared_error(actual, predicted))
    return {
        "r_squared": float(r2_score(actual, predicted)) if len(actual) > 1 else 0.0,
        "mae": float(mean_absolute_error(actual, predicted)),
        "mse": mse,
        "rmse": math.sqrt(mse),
    }


def calculate_recommendations(predicted_sales, stock_on_hand, reorder_level, safety_stock=0):
    """Return a reorder-level-aware target and the required purchase quantity."""
    target = max(math.ceil(max(0, float(predicted_sales)) + float(safety_stock)), int(reorder_level))
    return target, max(0, target - int(stock_on_hand))


def _prediction_row(history):
    latest = history.sort_values("period").iloc[-1]
    target_period = int(latest.period) + 1
    target_month = (target_period % 12) + 1
    last_year = history.loc[history.period == target_period - 12, "units_shipped"]
    last_year_actual = float(last_year.iloc[0]) if not last_year.empty else float("nan")
    has_last_year = int(pd.notna(last_year_actual))
    values = {
        "last_year_same_month": last_year_actual if has_last_year else float(latest.units_shipped),
        "has_last_year": has_last_year, "previous_sales": float(latest.units_shipped),
        "stock_on_hand": float(latest.stock_on_hand),
    }
    values.update(_month_feature_values(target_month))
    return pd.DataFrame([values], columns=MODEL_FEATURES), latest, target_month, last_year_actual


def safety_stock_for_latest_run():
    """Calculate 1.28 standard deviations of error from the latest fitted run."""
    run = TrainingRun.objects.order_by("-created_at").first()
    return 0.0 if run is None else Z * float(run.rmse)


def update_latest_predictions(model, frame, safety_stock=0):
    """Persist current next-month recommendations for every warehouse/SKU pair."""
    for _, history in frame.groupby(["warehouse_id", "sku"]):
        features, latest, _, last_year = _prediction_row(history)
        predicted = (
            float(history.units_shipped.tail(3).mean())
            if model is None or pd.isna(last_year)
            else max(0, float(model.predict(features)[0]))
        )
        inventory, restock = calculate_recommendations(
            predicted, latest.stock_on_hand, latest.reorder_level, safety_stock
        )
        StockLedger.objects.filter(id=int(latest.id)).update(
            predicted_demand=round(predicted, 2), recommended_inventory=inventory,
            recommended_restock=restock,
        )


def fit_forecaster(persist=True, safety_buffer=0):
    """Chronologically evaluate LinearRegression, then refit all available rows."""
    global _MODEL_CACHE, _CACHE_METRICS
    frame = sales_history_frame()
    usable = build_feature_rows(frame)
    empty_metrics = {
        "r_squared": 0, "mae": 0, "mse": 0, "rmse": 0,
        "baseline_r_squared": 0, "baseline_mae": 0,
        "baseline_last_month_mae": 0, "observations": len(usable), "backtest_data": [],
    }
    if len(usable) < MIN_MODEL_ROWS:
        if persist:
            update_latest_predictions(None, frame, safety_stock_for_latest_run())
        return None, empty_metrics, frame

    train, test = chronological_split(usable)
    if train.empty or test.empty:
        train, test = usable, usable.iloc[0:0]
    if test.empty:
        metrics = empty_metrics.copy()
    else:
        evaluation_model = LinearRegression().fit(train[MODEL_FEATURES], train.target_sales)
        estimate = evaluation_model.predict(test[MODEL_FEATURES])
        metrics = _metrics(test.target_sales, estimate)
        same_last_year = test[test.has_last_year == 1]
        baseline = _metrics(same_last_year.target_sales, same_last_year.last_year_actual) if not same_last_year.empty else {"r_squared": 0, "mae": 0}
        last_month = _metrics(test.target_sales, test.previous_sales)
        backtest_data = [
            {"period": int(row.target_period), "actual": float(row.target_sales), "predicted": float(prediction)}
            for (_, row), prediction in zip(test.iterrows(), estimate)
        ]
        metrics.update(
            baseline_r_squared=baseline["r_squared"], baseline_mae=baseline["mae"],
            baseline_last_month_mae=last_month["mae"], observations=len(usable),
            backtest_data=backtest_data,
        )

    model = LinearRegression().fit(usable[MODEL_FEATURES], usable.target_sales)
    _MODEL_CACHE, _CACHE_METRICS = model, metrics
    if persist:
        run = TrainingRun.objects.create(**metrics, safety_buffer=safety_buffer)
        update_latest_predictions(model, frame, Z * float(run.rmse))
    return model, metrics, frame


def forecast_one(warehouse_id, sku):
    """Forecast one warehouse/SKU, using a three-month fallback for limited history."""
    if _MODEL_CACHE is None:
        fit_forecaster(persist=False)
    frame = sales_history_frame()
    history = frame[(frame.warehouse_id == str(warehouse_id)) & (frame.sku == sku)].sort_values("period")
    if history.empty:
        return None
    features, latest, month, last_year = _prediction_row(history)
    limited = len(history) < 12 or pd.isna(last_year) or _MODEL_CACHE is None
    predicted = float(history.units_shipped.tail(3).mean()) if limited else max(0, float(_MODEL_CACHE.predict(features)[0]))
    inventory, restock = calculate_recommendations(
        predicted, latest.stock_on_hand, latest.reorder_level, safety_stock_for_latest_run()
    )
    return {
        "row": latest, "next_month": month, "predicted_demand": round(predicted, 2),
        "recommended_inventory": inventory, "recommended_restock": restock,
        "metrics": _CACHE_METRICS or {"r_squared": 0, "mae": 0, "mse": 0, "rmse": 0, "baseline_mae": 0, "baseline_last_month_mae": 0},
        "last_year_sales": None if pd.isna(last_year) else last_year,
        "last_month_sales": float(latest.units_shipped), "limited_history": limited,
    }
