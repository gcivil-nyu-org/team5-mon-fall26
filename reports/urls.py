from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("reports/new/", views.report_fare, name="report_fare"),
    path("reports/", views.my_reports, name="my_reports"),
    path("reports/<int:report_id>/edit/", views.edit_report, name="edit_report"),
    path("reports/<int:report_id>/delete/", views.delete_report, name="delete_report"),
]
