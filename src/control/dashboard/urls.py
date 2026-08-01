from django.urls import path

from control.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("jobs/", views.jobs_panel, name="jobs_panel"),
    path("configs/run-selected/", views.run_selected, name="run_selected"),
    path("configs/<int:pk>/run/", views.run_now, name="run_now"),
    path("jobs/<int:pk>/cancel/", views.cancel_job, name="cancel_job"),
    path("lots/", views.lots_list, name="lots_list"),
    path("lots/<str:id>/", views.lot_detail, name="lot_detail"),
]
