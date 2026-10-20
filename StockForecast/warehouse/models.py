from django.db import models

class StockLedger(models.Model):
    warehouse_id = models.CharField(max_length=40)
    warehouse_name = models.CharField(max_length=120)
    sku = models.CharField(max_length=50)
    product_name = models.CharField(max_length=160)
    category = models.CharField(max_length=80)
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    units_shipped = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    stock_on_hand = models.PositiveIntegerField()
    reorder_level = models.PositiveIntegerField()
    season = models.CharField(max_length=40)
    predicted_demand = models.FloatField(null=True, blank=True)
    recommended_inventory = models.PositiveIntegerField(default=0)
    recommended_restock = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["sku", "month", "year", "warehouse_id"], name="unique_sku_period_warehouse")]
        ordering = ["warehouse_name", "sku", "year", "month"]

    def __str__(self):
        return f"{self.warehouse_id} / {self.sku} / {self.month}-{self.year}"

    @property
    def month_name(self):
        return (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        )[self.month - 1]

class TrainingRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    r_squared = models.FloatField(default=0)
    mae = models.FloatField(default=0)
    mse = models.FloatField(default=0)
    rmse = models.FloatField(default=0)
    baseline_r_squared = models.FloatField(default=0)
    baseline_mae = models.FloatField(default=0)
    baseline_last_month_mae = models.FloatField(default=0)
    backtest_data = models.JSONField(default=list, blank=True)
    observations = models.PositiveIntegerField(default=0)
    safety_buffer = models.DecimalField(max_digits=5, decimal_places=2, default=0)
