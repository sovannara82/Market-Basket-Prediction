from django.contrib import admin
from .models import StockLedger, TrainingRun

@admin.register(StockLedger)
class StockLedgerAdmin(admin.ModelAdmin):
    list_display = ("warehouse_id", "sku", "year", "month", "units_shipped", "stock_on_hand", "recommended_restock")
    list_filter = ("warehouse_name", "category", "season")
    search_fields = ("sku", "product_name", "warehouse_name")

admin.site.register(TrainingRun)
