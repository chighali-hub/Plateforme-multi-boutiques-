"""Parametres de la plateforme, journal d'audit et informations publiques."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.helpers import error_code
from apps.core.audit import log_action
from apps.core.models import AuditAction, AuditLog, PlatformSettings

pytestmark = pytest.mark.django_db
SETTINGS = "/api/v1/admin/settings/"
AUDIT = "/api/v1/admin/audit-logs/"
PLATFORM_INFO = "/api/v1/public/platform-info/"
NOUAKCHOTT = ZoneInfo("Africa/Nouakchott")


# --- Parametres ---------------------------------------------------------------------
def test_get_settings(admin_client, platform_settings):
    response = admin_client.get(SETTINGS)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "admin_whatsapp",
        "admin_contact_email",
        "trial_months",
        "deposit_percent",
        "updated_at",
        "updated_by",
    }
    assert body["admin_whatsapp"] == "22334455"
    assert (body["trial_months"], body["deposit_percent"], body["updated_by"]) == (1, 30, None)


def test_patch_settings_updates_values_and_audit(admin_client):
    payload = {
        "admin_whatsapp": "+222 36 12 34 56",
        "admin_contact_email": "Contact@Plateforme.MR",
        "trial_months": 2,
        "deposit_percent": 50,
    }

    response = admin_client.patch(SETTINGS, payload, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["admin_whatsapp"] == "36123456"
    assert body["admin_contact_email"] == "contact@plateforme.mr"
    assert (body["trial_months"], body["deposit_percent"]) == (2, 50)
    assert body["updated_by"] == {"id": admin_client.user.pk, "email": admin_client.user.email}
    assert PlatformSettings.load().deposit_percent == 50
    changes = AuditLog.objects.get(action=AuditAction.SETTINGS_UPDATED).metadata["changes"]
    assert changes["trial_months"] == {"old": 1, "new": 2}
    assert changes["admin_whatsapp"] == {"old": "", "new": "36123456"}


@pytest.mark.parametrize(
    "payload",
    [
        {"admin_whatsapp": "12345678"},
        {"admin_whatsapp": "3612"},
        {"admin_contact_email": "pas-un-email"},
        {"trial_months": -1},
        {"trial_months": 13},
        {"deposit_percent": 0},
        {"deposit_percent": 101},
    ],
)
def test_patch_settings_invalid_values_return_400(admin_client, payload):
    response = admin_client.patch(SETTINGS, payload, format="json")

    assert response.status_code == 400 and error_code(response) == "VALIDATION_ERROR"
    assert set(payload) <= set(response.json()["error"]["details"])
    assert not AuditLog.objects.exists()


@pytest.mark.parametrize("value", [0, 12])
def test_patch_trial_months_bounds_are_accepted(admin_client, value):
    response = admin_client.patch(SETTINGS, {"trial_months": value}, format="json")
    assert response.status_code == 200 and response.json()["trial_months"] == value


def test_patch_settings_applies_to_next_approval(admin_client, make_shop):
    admin_client.patch(SETTINGS, {"trial_months": 3}, format="json")
    shop = make_shop("PENDING")

    body = admin_client.post(f"/api/v1/admin/shops/{shop.pk}/approve/").json()

    assert body["days_left"] >= 89


def test_patch_empty_body_changes_nothing(admin_client):
    response = admin_client.patch(SETTINGS, {}, format="json")

    assert response.status_code == 200
    assert not AuditLog.objects.exists()


def test_settings_put_is_not_allowed(admin_client):
    response = admin_client.put(SETTINGS, {}, format="json")
    assert response.status_code == 405 and error_code(response) == "METHOD_NOT_ALLOWED"


# --- Informations publiques ---------------------------------------------------------
def test_platform_info_is_public(platform_settings):
    response = APIClient().get(PLATFORM_INFO)

    assert response.status_code == 200
    assert response.json() == {
        "admin_whatsapp": "22334455",
        "admin_whatsapp_url": "https://wa.me/22222334455",
        "admin_contact_email": "contact@plateforme.mr",
        "deposit_percent": 30,
    }


def test_platform_info_without_contact(db):
    body = APIClient().get(PLATFORM_INFO).json()

    assert (body["admin_whatsapp"], body["admin_whatsapp_url"], body["admin_contact_email"]) == (
        "",
        "",
        "",
    )


def test_platform_info_ignores_invalid_token(platform_settings):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer jeton-invalide")

    assert client.get(PLATFORM_INFO).status_code == 200


def test_platform_info_reflects_new_settings(admin_client):
    admin_client.patch(SETTINGS, {"deposit_percent": 45}, format="json")

    assert APIClient().get(PLATFORM_INFO).json()["deposit_percent"] == 45


# --- Journal d'audit ----------------------------------------------------------------
@pytest.fixture
def audit_entries(admin_user, make_shop):
    shop = make_shop("ACTIVE")
    entries = {
        "approved": log_action(admin_user, AuditAction.SHOP_APPROVED, target=shop),
        "submitted": log_action(shop.owner, AuditAction.SHOP_SUBMITTED, target=shop),
        "settings": log_action(
            admin_user,
            AuditAction.SETTINGS_UPDATED,
            target_type="platform_settings",
            metadata={"changes": {}},
        ),
    }
    AuditLog.objects.filter(pk=entries["approved"].pk).update(
        created_at=datetime(2026, 1, 10, 12, 0, tzinfo=NOUAKCHOTT)
    )
    return shop, entries


def test_audit_log_list_format(admin_client, audit_entries):
    response = admin_client.get(AUDIT)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    item = body["results"][0]
    assert set(item) == {
        "id",
        "action",
        "actor",
        "target_type",
        "target_id",
        "metadata",
        "ip_address",
        "created_at",
    }
    assert item["action"] == "SETTINGS_UPDATED"
    assert item["actor"] == {"id": admin_client.user.pk, "email": admin_client.user.email}


def test_audit_log_filters(admin_client, audit_entries):
    shop, entries = audit_entries

    def ids(params):
        return {item["id"] for item in admin_client.get(AUDIT, params).json()["results"]}

    assert ids({"action": "SHOP_SUBMITTED"}) == {entries["submitted"].pk}
    assert ids({"actor": shop.owner.pk}) == {entries["submitted"].pk}
    assert ids({"target_type": "shop", "target_id": shop.pk}) == {
        entries["approved"].pk,
        entries["submitted"].pk,
    }
    assert ids({"date_from": "2026-01-10", "date_to": "2026-01-10"}) == {entries["approved"].pk}
    assert entries["approved"].pk not in ids({"date_from": "2026-01-11"})


@pytest.mark.parametrize(
    "params",
    [
        {"action": "DELETE_EVERYTHING"},
        {"actor": "abc"},
        {"target_id": "x"},
        {"date_to": "2026-13-01"},
        {"date_from": "2026-02-01", "date_to": "2026-01-01"},
    ],
)
def test_audit_log_invalid_filters_return_400(admin_client, params):
    response = admin_client.get(AUDIT, params)
    assert response.status_code == 400 and error_code(response) == "VALIDATION_ERROR"


def test_audit_log_records_ip_of_admin_action(admin_client, make_shop):
    shop = make_shop("PENDING")
    admin_client.post(f"/api/v1/admin/shops/{shop.pk}/approve/", REMOTE_ADDR="41.188.10.20")

    item = admin_client.get(AUDIT, {"action": "SHOP_APPROVED"}).json()["results"][0]

    assert item["ip_address"] == "41.188.10.20"
    assert item["target_type"] == "shop" and item["target_id"] == shop.pk
