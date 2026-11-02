# Sample data

`inventory_forecast_demo.xlsx` is a compact, fictional Excel workbook for trying the upload flow. It has 24 monthly records (January 2024 to December 2025) for a generic warehouse and a generic product.

It uses the workbook columns required by the application and contains no personal, customer, supplier, employee, or production data. Upload it from the application's **Upload** page after running migrations.

To regenerate the sample deterministically, run `python scripts/build_sample.py` from the repository root.
