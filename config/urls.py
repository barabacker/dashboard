from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("control.urls")),
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
]
