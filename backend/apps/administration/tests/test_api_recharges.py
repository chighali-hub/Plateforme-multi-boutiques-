"""Recharge des boutiques : apercu, recharge, historiques (RG-20 a RG-24)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.tests.helpers import error_code
from apps.administration.models import Recharge
from apps.administration.tests.factories import RechargeFactory
from apps.core.models import AuditAction, AuditLog
from apps.notifications.models import Notification, NotificationType

pytestmark = pytest.mark.django_db
NOUAKCHOTT = ZoneInfo("Africa/Nouakchott")
SHOPS = "/api/v1/admin/shops/"
ALL_RECHARGES = "/api/v1/admin/recharges/"


def _preview(shop):
    return f"{SHOPS}{shop.pk}/recharge-preview/"


def _recharge(shop):
    return f"{SHOPS}{shop.pk}/recharge/"


# --- Apercu -------------------------------------------------------------------------
def test_preview_for_active_shop_adds_to_expiry(admin_client, make_shop, freeze_now):
    now = freeze_now(datetime(2026, 11, 20, 15, 40, tzinfo=NOUAKCHOTT))
    shop = make_shop("ACTIVE", expires_at=now + timedelta(days=30))

    response = admin_client.get(_preview(shop), {"duration_months": 12})

    assert response.status_code == 200
    assert response.json() == {
        "current_expires_at": "2026-12-20T15:40:00Z",
        "base_date": "2026-12-20T15:40:00Z",
        "new_expires_at": "2027-12-20T15:40:00Z",
        "is_currently_expired": False,
    }
    shop.refresh_from_db()
    assert shop.expires_at == now + timedelta(days=30)
    assert not Recharge.objects.exists()


def test_preview_for_expired_shop_starts_today(admin_client, make_shop, freeze_now):
    now = freeze_now(datetime(2026, 11, 20, 9, 0, tzinfo=NOUAKCHOTT))
    shop = make_shop("EXPIRED", expires_at=now - timedelta(days=3))

    body = admin_client.get(_preview(shop), {"target_date": "2031-11-20"}).json()

    assert body["is_currently_expired"] is True
    assert body["base_date"] == "2026-11-20T09:00:00Z"
    assert body["new_expires_at"] == "2031-11-20T23:59:59Z"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"duration_months": 3, "target_date": "2031-01-01"},
        {"duration_months": 0},
        {"duration_months": 121},
        {"duration_months": "abc"},
        {"target_date": "20-11-2031"},
        {"target_date": "2000-01-01"},
    ],
)
def test_preview_invalid_parameters_return_400(admin_client, make_shop, params):
    response = admin_client.get(_preview(make_shop("ACTIVE")), params)

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"


@pytest.mark.parametrize("state", ["ONBOARDING", "PENDING", "REJECTED"])
def test_preview_for_not_approved_shop_returns_409(admin_client, make_shop, state):
    response = admin_client.get(_preview(make_shop(state)), {"duration_months": 1})

    assert response.status_code == 409
    assert error_code(response) == "INVALID_STATE_TRANSITION"


def test_preview_unknown_shop_returns_404(admin_client):
    response = admin_client.get(f"{SHOPS}999999/recharge-preview/", {"duration_months": 1})
    assert response.status_code == 404


# --- Recharge -----------------------------------------------------------------------
def test_recharge_with_months(admin_client, make_shop, django_capture_on_commit_callbacks):
    shop = make_shop("ACTIVE", last_expiry_reminder_days=7)
    previous = shop.expires_at
    payload = {"duration_months": 12, "amount_received": 12000, "note": "Paiement Bankily du 18/12"}

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(_recharge(shop), payload, format="json")

    assert response.status_code == 201
    body = response.json()
    recharge = Recharge.objects.get()
    assert body["recharge"]["id"] == recharge.pk
    assert body["recharge"]["duration_months"] == 12
    assert body["recharge"]["amount_received"] == 12000
    assert body["recharge"]["note"] == "Paiement Bankily du 18/12"
    assert body["recharge"]["performed_by"] == {
        "id": admin_client.user.pk,
        "email": admin_client.user.email,
    }
    assert body["shop"]["id"] == shop.pk and body["shop"]["state"] == "ACTIVE"
    assert body["shop"]["days_left"] > 360
    shop.refresh_from_db()
    assert shop.expires_at == recharge.new_expires_at
    assert recharge.previous_expires_at == previous
    assert shop.last_expiry_reminder_days is None
    notification = Notification.objects.get(
        recipient=shop.owner, type=NotificationType.SHOP_RECHARGED
    )
    assert set(notification.data) == {"previous_expires_at", "new_expires_at"}
    entry = AuditLog.objects.get(action=AuditAction.SHOP_RECHARGED)
    assert entry.metadata["duration_months"] == 12
    assert entry.metadata["amount_received"] == 12000
    assert mail.outbox[-1].to == [shop.owner.email]


def test_recharge_with_target_date_reactivates_expired_shop(admin_client, make_shop):
    shop = make_shop("EXPIRED")

    response = admin_client.post(
        _recharge(shop), {"target_date": "2031-11-20", "amount_received": 50000}, format="json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["recharge"]["duration_months"] is None
    assert body["recharge"]["note"] == ""
    assert body["shop"]["state"] == "ACTIVE"
    shop.refresh_from_db()
    assert shop.expires_at.astimezone(NOUAKCHOTT).date() == date(2031, 11, 20)


def test_recharge_of_blocked_shop_keeps_it_blocked(admin_client, make_shop):
    shop = make_shop("BLOCKED")

    response = admin_client.post(_recharge(shop), {"duration_months": 1}, format="json")

    assert response.status_code == 201
    assert response.json()["shop"]["state"] == "BLOCKED"


def test_recharge_without_amount_and_note(admin_client, make_shop):
    response = admin_client.post(
        _recharge(make_shop("ACTIVE")),
        {"duration_months": 1, "amount_received": None},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["recharge"]["amount_received"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"duration_months": 1, "target_date": "2031-01-01"},
        {"duration_months": 0},
        {"duration_months": 121},
        {"duration_months": 1, "amount_received": -5},
        {"duration_months": 1, "note": "x" * 256},
        {"target_date": "2001-01-01"},
    ],
)
def test_recharge_invalid_payload_changes_nothing(admin_client, make_shop, payload):
    shop = make_shop("ACTIVE")
    expires_at = shop.expires_at

    response = admin_client.post(_recharge(shop), payload, format="json")

    assert response.status_code == 400 and error_code(response) == "VALIDATION_ERROR"
    shop.refresh_from_db()
    assert shop.expires_at == expires_at
    assert not Recharge.objects.exists()
    assert not Notification.objects.exists()


@pytest.mark.parametrize("state", ["ONBOARDING", "PENDING", "REJECTED"])
def test_recharge_not_approved_shop_returns_409(admin_client, make_shop, state):
    response = admin_client.post(_recharge(make_shop(state)), {"duration_months": 1}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"current_state": state}
    assert not Recharge.objects.exists()


def test_recharged_shop_sees_its_history_without_private_fields(admin_client, make_shop_client):
    client = make_shop_client("ACTIVE")
    admin_client.post(
        _recharge(client.shop), {"duration_months": 2, "note": "secret"}, format="json"
    )

    item = client.get("/api/v1/shop/recharges/").json()["results"][0]

    assert item["duration_months"] == 2
    assert "note" not in item and "amount_received" not in item


# --- Historiques --------------------------------------------------------------------
def test_shop_recharge_history_is_paginated_and_isolated(admin_client, make_shop):
    shop, other = make_shop("ACTIVE"), make_shop("ACTIVE")
    first = RechargeFactory(shop=shop)
    second = RechargeFactory(shop=shop)
    RechargeFactory(shop=other)

    response = admin_client.get(f"{SHOPS}{shop.pk}/recharges/")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [item["id"] for item in body["results"]] == [second.pk, first.pk]
    assert "shop" not in body["results"][0]
    assert admin_client.get(f"{SHOPS}999999/recharges/").status_code == 404


def test_all_recharges_filters(admin_client, make_shop):
    shop, other = make_shop("ACTIVE"), make_shop("ACTIVE")
    recent = RechargeFactory(shop=shop)
    old = RechargeFactory(shop=other)
    Recharge.objects.filter(pk=old.pk).update(
        created_at=datetime(2026, 1, 15, 23, 30, tzinfo=NOUAKCHOTT)
    )

    everything = admin_client.get(ALL_RECHARGES).json()
    by_shop = admin_client.get(ALL_RECHARGES, {"shop": other.pk}).json()
    january = admin_client.get(
        ALL_RECHARGES, {"date_from": "2026-01-15", "date_to": "2026-01-15"}
    ).json()
    since_february = admin_client.get(ALL_RECHARGES, {"date_from": "2026-02-01"}).json()

    assert everything["count"] == 2
    assert everything["results"][0]["shop"] == {"id": shop.pk, "name": shop.name}
    assert [item["id"] for item in by_shop["results"]] == [old.pk]
    assert [item["id"] for item in january["results"]] == [old.pk]
    assert [item["id"] for item in since_february["results"]] == [recent.pk]


@pytest.mark.parametrize(
    "params",
    [
        {"shop": "abc"},
        {"date_from": "15/01/2026"},
        {"date_from": "2026-02-01", "date_to": "2026-01-01"},
    ],
)
def test_all_recharges_invalid_filters_return_400(admin_client, params):
    response = admin_client.get(ALL_RECHARGES, params)
    assert response.status_code == 400 and error_code(response) == "VALIDATION_ERROR"


def test_recharge_history_page_out_of_range_returns_404(admin_client):
    response = admin_client.get(ALL_RECHARGES, {"page": 5})
    assert response.status_code == 404 and error_code(response) == "NOT_FOUND"


def test_recharge_dashboard_counts_this_month(admin_client, make_shop):
    RechargeFactory(shop=make_shop("ACTIVE"), amount_received=3000)

    body = admin_client.get("/api/v1/admin/dashboard/").json()

    assert body["recharges"]["count"] == 1 and body["recharges"]["amount_received"] == 3000
    assert body["recharges"]["month"] == timezone.now().strftime("%Y-%m")
