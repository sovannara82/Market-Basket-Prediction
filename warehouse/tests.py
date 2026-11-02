from io import BytesIO

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from .cleaning import prepare_workbook
from .forecasting import (
    MODEL_FEATURES, MONTH_FEATURES, build_feature_rows, calculate_recommendations, chronological_split,
    fit_forecaster, forecast_one, invalidate_model_cache, sales_history_frame,
)
from .models import StockLedger, TrainingRun

HEADERS = ["Warehouse ID", "Warehouse Name", "SKU", "Product Name", "Category", "Month", "Year", "Units Shipped", "Unit Cost", "Stock On Hand", "Reorder Level", "Season"]


class ForecastingTests(TestCase):
    def setUp(self):
        invalidate_model_cache()

    def _history(self, sku="HISTORY", months=24, stock=5, reorder=10):
        for offset in range(months):
            year, month = divmod(offset, 12)
            StockLedger.objects.create(
                warehouse_id="W", warehouse_name="Warehouse", sku=sku, product_name="TV",
                category="C", month=month + 1, year=2024 + year,
                units_shipped=20 + month + year * 2, unit_cost=1, stock_on_hand=stock,
                reorder_level=reorder, season="Peak",
            )

    def _workbook(self, rows):
        stream = BytesIO()
        pd.DataFrame(rows, columns=HEADERS).to_excel(stream, index=False)
        stream.seek(0)
        return stream

    def test_rollover_and_last_year_alignment(self):
        frame = pd.DataFrame([
            {"warehouse_id": "W", "sku": "ABC", "year": 2024, "month": 12, "units_shipped": 10, "stock_on_hand": 4},
            {"warehouse_id": "W", "sku": "ABC", "year": 2025, "month": 1, "units_shipped": 15, "stock_on_hand": 5},
            {"warehouse_id": "W", "sku": "ABC", "year": 2025, "month": 12, "units_shipped": 20, "stock_on_hand": 6},
            {"warehouse_id": "W", "sku": "ABC", "year": 2026, "month": 1, "units_shipped": 25, "stock_on_hand": 7},
        ])
        frame["period"] = frame.year * 12 + frame.month - 1
        january_2026 = build_feature_rows(frame).query("target_sales == 25").iloc[0]
        self.assertEqual(january_2026.last_year_same_month, 15)
        self.assertEqual(january_2026.previous_sales, 20)

    def test_month_features_and_first_year_rows_are_kept(self):
        self._history(months=24)
        rows = build_feature_rows(sales_history_frame())
        self.assertTrue(set(MONTH_FEATURES).issubset(rows.columns))
        self.assertEqual(len(rows), 23)
        self.assertGreater(len(rows), 12)
        self.assertEqual(int(rows.iloc[0].has_last_year), 0)
        self.assertEqual(rows.iloc[0].last_year_same_month, rows.iloc[0].previous_sales)

    def test_model_features_exclude_calendar_month_columns(self):
        self.assertFalse(any(name.startswith("month_") for name in MODEL_FEATURES))

    def test_chronological_split_and_restock_rule(self):
        rows = pd.DataFrame({"origin_period": [1, 2, 3, 4, 5]})
        train, test = chronological_split(rows)
        self.assertLess(train.origin_period.max(), test.origin_period.min())
        target, restock = calculate_recommendations(10.1, 5, 12, 2)
        self.assertEqual((target, restock), (13, 8))
        self.assertGreater(calculate_recommendations(10, 83, 112, 0)[1], 0)

    def test_thirteen_month_history_uses_fallback_without_crashing(self):
        self._history(months=13)
        outcome = forecast_one("W", "HISTORY")
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome["limited_history"])
        self.assertEqual(outcome["predicted_demand"], 27.67)
        response = self.client.post(reverse("forecasts"), {"warehouse": "W", "sku": "HISTORY"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Limited history")

    def test_backtest_data_has_real_holdout_points(self):
        self._history()
        model, metrics, _ = fit_forecaster(True)
        self.assertIsNotNone(model)
        run = TrainingRun.objects.latest("created_at")
        self.assertEqual(len(run.backtest_data), 3)
        self.assertEqual(len(metrics["backtest_data"]), 3)
        self.assertTrue(all(point["actual"] != 0 for point in run.backtest_data))
        self.assertTrue(all(point["predicted"] != 0 for point in run.backtest_data))

    def test_upload_too_little_data_has_clear_message(self):
        row = [" W ", "Warehouse", "sku1", "TV", "C", 1, 2025, 10, 1, 2, 3, "Peak"]
        upload = SimpleUploadedFile("history.xlsx", self._workbook([row]).getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response = self.client.post(reverse("intake"), {"workbook": upload}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not enough history")
        record = StockLedger.objects.get()
        self.assertEqual(record.sku, "SKU1")
        self.assertEqual(record.warehouse_id, "W")
        self.assertEqual(record.season, "Peak")
        self.assertIsNotNone(record.predicted_demand)

    def test_invalid_upload_shows_form_error(self):
        upload = SimpleUploadedFile("history.csv", b"not,a,workbook", "text/csv")
        response = self.client.post(reverse("intake"), {"workbook": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please upload an Excel .xlsx workbook.")

    def test_cleaning_drops_missing_units_and_prefers_pair_median(self):
        rows = [
            ["W", "Warehouse", "SKU1", "TV", "C", 1, 2025, 10, 10, 20, 30, "Peak"],
            ["W", "Warehouse", "SKU1", "TV", "C", 2, 2025, 11, 10, None, None, "Peak"],
            ["W", "Warehouse", "SKU1", "TV", "C", 3, 2025, 12, 10, 20, 30, "Peak"],
            ["W", "Warehouse", "SKU2", "USB", "C", 3, 2025, None, 1, 2, 3, "Dry"],
        ]
        result = prepare_workbook(self._workbook(rows))
        self.assertEqual(result.report["rows_missing_units"], 1)
        self.assertEqual(len(result.records), 3)
        february = result.records[result.records.month == 2].iloc[0]
        self.assertEqual(february.stock_on_hand, 20)
        self.assertEqual(february.reorder_level, 30)
        self.assertEqual(february.season, "Peak")
        self.assertEqual(result.report["same_pair_values_filled"], 2)

    def test_cleaning_accepts_complete_integer_columns_with_fractional_medians(self):
        rows = [
            ["W", "Warehouse", "SKU1", "TV", "C", 1, 2025, 10, 10, 20, 30, "Dry"],
            ["W", "Warehouse", "SKU2", "USB", "C", 2, 2025, 11, 12, 23, 33, "Dry"],
        ]
        result = prepare_workbook(self._workbook(rows))
        self.assertEqual(result.report["same_pair_values_filled"], 0)
        self.assertEqual(result.report["global_values_filled"], 0)
        self.assertEqual(result.report["missing_values_fixed"], 0)
        self.assertEqual(len(result.records), 2)

    def test_bad_numeric_filters_and_pagination_keep_filters(self):
        for index in range(16):
            StockLedger.objects.create(warehouse_id="W", warehouse_name="Warehouse", sku=f"SKU{index:02}", product_name="TV", category="C", month=1, year=2025, units_shipped=10, unit_cost=1, stock_on_hand=2, reorder_level=3, season="Dry")
        response = self.client.get(reverse("products"), {"month": "abc", "year": "abc", "warehouse": "W", "q": "SKU", "sort": "sku"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "warehouse=W")
        self.assertContains(response, "q=SKU")

    def test_no_train_url_or_button(self):
        with self.assertRaises(NoReverseMatch):
            reverse("train")
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Train model")
