from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

urlpatterns = [
    path("", lambda request: redirect("dashboard:index")),
    path("admin/", admin.site.urls),
    path("dashboard/", include("control.dashboard.urls")),
]
