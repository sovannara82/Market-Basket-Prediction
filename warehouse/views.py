"""Views for data intake, dashboards, and inventory forecasts."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Sum
from django.shortcuts import render

from .cleaning import prepare_workbook, save_ledger
from .forecasting import fit_forecaster, forecast_one, sales_history_frame
from .forms import ForecastForm, WorkbookUploadForm
from .models import StockLedger, TrainingRun


MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)


def filtered(request):
    """Apply safe, user-selected filters without allowing invalid numeric values."""
    queryset = StockLedger.objects.all()
    for key, field in (
        ("warehouse", "warehouse_id"),
        ("category", "category"),
        ("season", "season"),
    ):
        if request.GET.get(key):
            queryset = queryset.filter(**{field: request.GET[key]})

    for key, field in (("month", "month"), ("year", "year")):
        value = request.GET.get(key, "")
        if value.isdigit():
            queryset = queryset.filter(**{field: int(value)})
    return queryset


def choices():
    return {
        "warehouses": StockLedger.objects.values(
            "warehouse_id", "warehouse_name"
        ).order_by("warehouse_id").distinct(),
        "categories": StockLedger.objects.values_list(
            "category", flat=True
        ).order_by("category").distinct(),
        "seasons": StockLedger.objects.values_list(
            "season", flat=True
        ).order_by("season").distinct(),
        "months": list(enumerate(MONTH_NAMES, 1)),
        "years": StockLedger.objects.values_list(
            "year", flat=True
        ).order_by("-year").distinct(),
    }


def _backtest_chart(run):
    points = (run.backtest_data if run else []) or []
    grouped = {}
    for point in points:
        grouped.setdefault(int(point["period"]), []).append(point)

    labels, actual, predicted = [], [], []
    for period, group in sorted(grouped.items()):
        year, month_zero = divmod(period, 12)
        labels.append(f"{MONTH_NAMES[month_zero]} {year}")
        actual.append(round(sum(point["actual"] for point in group) / len(group), 1))
        predicted.append(
            round(sum(point["predicted"] for point in group) / len(group), 1)
        )
    return {"labels": labels, "actual": actual, "predicted": predicted}


def charts(queryset, run=None):
    month = queryset.values("month").annotate(total=Sum("units_shipped")).order_by("month")
    category = (
        queryset.values("category")
        .annotate(total=Sum("units_shipped"))
        .order_by("category")
    )
    warehouse = (
        queryset.values("warehouse_name")
        .annotate(stock=Sum("stock_on_hand"), reorder=Sum("reorder_level"))
        .order_by("warehouse_name")
    )
    return {
        "monthly": {
            "labels": [MONTH_NAMES[item["month"] - 1] for item in month],
            "data": [item["total"] for item in month],
        },
        "categories": {
            "labels": [item["category"] for item in category],
            "data": [item["total"] for item in category],
        },
        "warehouse": {
            "labels": [item["warehouse_name"] for item in warehouse],
            "stock": [item["stock"] for item in warehouse],
            "reorder": [item["reorder"] for item in warehouse],
        },
        "accuracy": _backtest_chart(run),
    }


def dashboard(request):
    queryset = filtered(request)
    latest = TrainingRun.objects.order_by("-created_at").first()
    kpis = {
        "skus": queryset.values("sku").distinct().count(),
        "warehouses": queryset.values("warehouse_id").distinct().count(),
        "demand": queryset.aggregate(value=Avg("units_shipped"))["value"] or 0,
        "restock": queryset.aggregate(value=Sum("recommended_restock"))["value"] or 0,
        "r2": latest.r_squared if latest else 0,
        "mae": latest.mae if latest else 0,
        "baseline_mae": latest.baseline_mae if latest else 0,
        "baseline_last_month_mae": latest.baseline_last_month_mae if latest else 0,
    }
    context = {
        "filters": choices(),
        "active": request.GET,
        "charts": charts(queryset, latest),
        "recent": queryset.order_by("-year", "-month", "id")[:8],
        "kpis": kpis,
    }
    return render(request, "warehouse/dashboard.html", context)


def intake(request):
    result = None
    form = (
        WorkbookUploadForm(request.POST, request.FILES)
        if request.method == "POST"
        else WorkbookUploadForm()
    )
    if request.method == "POST" and form.is_valid():
        try:
            result = prepare_workbook(form.cleaned_data["workbook"])
            added, updated = save_ledger(result.records)
            model, metrics, frame = fit_forecaster(True)
            latest_pairs = frame.groupby(["warehouse_id", "sku"]).ngroups if not frame.empty else 0
            if model is None:
                messages.warning(
                    request,
                    f"Imported {added} new rows and refreshed {updated} existing rows. "
                    "There is not enough history to fit the regression yet; "
                    f"{latest_pairs} product forecasts use the last-three-month fallback.",
                )
            else:
                messages.success(
                    request,
                    f"Imported {added} new rows and refreshed {updated} existing rows. "
                    f"Generated forecasts for {latest_pairs} warehouse/product pairs from "
                    f"{metrics['observations']} historical intervals.",
                )
        except ValueError as error:
            messages.error(request, str(error))
    return render(request, "warehouse/intake.html", {"form": form, "result": result})


def _query_string(request, *remove):
    query = request.GET.copy()
    for key in remove:
        query.pop(key, None)
    return query.urlencode()


def products(request):
    queryset = filtered(request)
    if request.GET.get("q"):
        queryset = queryset.filter(sku__icontains=request.GET["q"]) | queryset.filter(
            product_name__icontains=request.GET["q"]
        )

    sort = request.GET.get("sort", "sku")
    allowed = {
        "sku", "product_name", "category", "warehouse_name", "units_shipped", "stock_on_hand",
    }
    if sort.lstrip("-") not in allowed:
        sort = "sku"
    queryset = queryset.order_by(sort, "id")
    context = {
        "page": Paginator(queryset, 15).get_page(request.GET.get("page")),
        "filters": choices(),
        "active": request.GET,
        "page_query": _query_string(request, "page"),
        "sort_query": _query_string(request, "page", "sort"),
        "sort": sort,
    }
    return render(request, "warehouse/products.html", context)


def _forecast_form(data=None):
    form = ForecastForm(data)
    form.fields["warehouse"].choices = [
        (item["warehouse_id"], item["warehouse_name"])
        for item in StockLedger.objects.values("warehouse_id", "warehouse_name")
        .order_by("warehouse_id")
        .distinct()
    ]
    form.fields["sku"].choices = [
        (sku, sku)
        for sku in StockLedger.objects.values_list("sku", flat=True)
        .order_by("sku")
        .distinct()
    ]
    return form


def forecasts(request):
    data = request.POST if request.method == "POST" else (request.GET if request.GET else None)
    form = _forecast_form(data)
    outcome = None
    if data and form.is_valid():
        values = form.cleaned_data
        if not StockLedger.objects.filter(
            warehouse_id=values["warehouse"], sku=values["sku"]
        ).exists():
            messages.error(request, "That warehouse and SKU combination does not exist.")
        else:
            outcome = forecast_one(values["warehouse"], values["sku"])
            outcome["next_month_name"] = MONTH_NAMES[outcome["next_month"] - 1]
            history = sales_history_frame(
                StockLedger.objects.filter(
                    warehouse_id=values["warehouse"], sku=values["sku"]
                )
            ).sort_values("period").tail(24)
            outcome["chart"] = {
                "labels": [
                    f"{MONTH_NAMES[int(row.month) - 1]} {int(row.year)}"
                    for _, row in history.iterrows()
                ] + [outcome["next_month_name"]],
                "actual": [
                    float(row.units_shipped) for _, row in history.iterrows()
                ] + [None],
                "prediction": [None] * len(history) + [outcome["predicted_demand"]],
            }
    return render(request, "warehouse/forecasts.html", {"form": form, "outcome": outcome})


def analytics(request):
    queryset = filtered(request)
    return render(
        request,
        "warehouse/analytics.html",
        {
            "filters": choices(),
            "active": request.GET,
            "charts": charts(queryset, TrainingRun.objects.order_by("-created_at").first()),
        },
    )
