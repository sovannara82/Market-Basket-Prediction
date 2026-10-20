# Inventory Forecast

Inventory Forecast is a Django dashboard that predicts next-month product demand for each warehouse and recommends how many units to order.

## Start

```powershell
cd StockForecast
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Upload `fixtures/stockforecast_sample.xlsx` at `http://127.0.0.1:8000/upload/`. A successful upload automatically fits the model and updates recommendations.

## Workbook columns

`Warehouse ID, Warehouse Name, SKU, Product Name, Category, Month, Year, Units Shipped, Unit Cost, Stock On Hand, Reorder Level, Season`

The importer uppercases warehouse IDs and SKUs, preserves supplied season labels, drops invalid shipped-unit rows, removes duplicate periods, and fills missing cost, stock, or reorder values from the same warehouse/SKU median before using a global median.

## Forecast method

The app uses scikit-learn `LinearRegression` to predict units shipped at month `t + 1`. Features are prior-month sales; sales in the same target month last year (or prior-month sales when unavailable); a `has_last_year` indicator; and stock on hand. Seasonality comes from the same-month-last-year value.

The newest three origin months are held out chronologically for evaluation. The dashboard compares model MAE against same-month-last-year and last-month baselines, and the accuracy chart displays only those held-out predictions. If a product has limited history or no fitted model is available, its prediction uses the mean of its latest three months.

## Restock rule

`safety_stock = 1.28 × latest model RMSE`

`target_inventory = max(ceil(predicted_sales + safety_stock), reorder_level)`

`units_to_order = max(0, target_inventory - stock_on_hand)`

The app shows **Restock now** exactly when `units_to_order > 0`.

## Tests

```powershell
python manage.py test
```
