from django.urls import path

from control import api

app_name = "control"

urlpatterns = [
    path("runs/claim/", api.claim, name="claim"),
    path("runs/<int:run_id>/logs/", api.logs, name="logs"),
    path("runs/<int:run_id>/heartbeat/", api.heartbeat, name="heartbeat"),
    path("runs/<int:run_id>/complete/", api.complete, name="complete"),
]
