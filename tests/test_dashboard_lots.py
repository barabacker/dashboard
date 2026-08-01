"""HTTP-level tests for the read-only lots pages — mirrors test_dashboard.py's shape, with a
mongomock collection injected in place of `control.services.lots.get_lots_collection`."""

from __future__ import annotations

import mongomock
import pytest
from bson import ObjectId
from django.urls import reverse

import control.services.lots as lots_module
from conftest import make_lot

pytestmark = pytest.mark.django_db


@pytest.fixture
def lots_collection(monkeypatch):
    collection = mongomock.MongoClient()["dashboard-test"]["lots"]
    monkeypatch.setattr(lots_module, "get_lots_collection", lambda: collection)
    return collection


def test_lots_list_requires_staff(client, lots_collection):
    response = client.get(reverse("dashboard:lots_list"))
    assert response.status_code == 302


def test_lots_list_renders_the_unfold_admin_chrome(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"))
    assert response.status_code == 200
    assert "Источники".encode() in response.content


def test_lots_list_shows_stored_lots(client, user, lots_collection):
    make_lot(lots_collection, lot_num="42")
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"))
    assert b"42" in response.content


def test_lots_list_filters_by_source(client, user, lots_collection):
    make_lot(lots_collection, lot_id="a", source="site-a", lot_num="AAA")
    make_lot(lots_collection, lot_id="b", source="site-b", lot_num="BBB")
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"), {"source": "site-a"})
    assert b"AAA" in response.content
    assert b"BBB" not in response.content


def test_lots_list_page_links_preserve_the_source_filter(
    client, user, lots_collection, monkeypatch
):
    monkeypatch.setattr(lots_module, "PAGE_SIZE", 1)
    make_lot(lots_collection, lot_id="a", source="site-a")
    make_lot(lots_collection, lot_id="b", source="site-a")
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"), {"source": "site-a"})
    assert b"source=site-a&page=2" in response.content


def test_lots_list_shows_the_navigation_link(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assert reverse("dashboard:lots_list").encode() in response.content
    assert "Лоты".encode() in response.content


def test_lots_list_links_to_the_detail_page(client, user, lots_collection):
    stored = make_lot(lots_collection)
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"))
    assert reverse("dashboard:lot_detail", args=[str(stored["_id"])]).encode() in response.content


def test_lot_detail_renders_the_main_fields(client, user, lots_collection):
    stored = make_lot(
        lots_collection,
        debtor="ООО «Должник»",
        lot_url="https://bankrupt.centerr.ru/lot/1",
    )
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=[str(stored["_id"])]))
    assert response.status_code == 200
    assert "ООО «Должник»".encode() in response.content
    assert b"https://bankrupt.centerr.ru/lot/1" in response.content


def test_lot_detail_renders_json_fields(client, user, lots_collection):
    stored = make_lot(lots_collection, attachments=[{"name": "file.pdf"}])
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=[str(stored["_id"])]))
    assert b"file.pdf" in response.content


def test_lot_detail_404s_for_an_unknown_id(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=[str(ObjectId())]))
    assert response.status_code == 404


def test_lot_detail_404s_for_a_malformed_id(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=["not-an-id"]))
    assert response.status_code == 404
