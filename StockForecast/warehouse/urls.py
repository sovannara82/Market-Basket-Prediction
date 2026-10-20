from django.urls import path
from . import views
urlpatterns = [path("", views.dashboard, name="dashboard"), path("upload/", views.intake, name="intake"), path("products/", views.products, name="products"), path("forecasts/", views.forecasts, name="forecasts"), path("analytics/", views.analytics, name="analytics")]
