"""Onglet « Charger mon compte » : informations et historique des recharges.

Voir 03-reference-api.md section 5 (recharge-info, recharges).
"""

from datetime import timedelta
from urllib.parse import unquote

import pytest
from django.utils import timezone

from apps.accounts.tests.helpers import error_code
from apps.administration.tests.factories import RechargeFactory

pytestmark = pytest.mark.django_db
INFO = "/api/v1/shop/recharge-info/"
HISTORY = "/api/v1/shop/recharges/"


def test_recharge_info_returns_expiry_and_prefilled_whatsapp_link(
    make_shop_client, admin_whatsapp, freeze_now
):
    now = freeze_now(timezone.now())
    client = make_shop_client("ACTIVE", expires_at=now + timedelta(days=28, hours=3))
    shop = client.shop

    response = client.get(INFO)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "expires_at",
        "days_left",
        "admin_whatsapp",
        "whatsapp_url",
        "admin_contact_email",
    }
    assert body["days_left"] == 29
    assert body["admin_whatsapp"] == "22334455"
    assert body["admin_contact_email"] == "contact@plateforme.mr"
    assert body["whatsapp_url"].startswith("https://wa.me/22222334455?text=")
    text = unquote(body["whatsapp_url"].split("?text=", 1)[1])
    assert text == (
        f"Bonjour, je souhaite recharger le compte de la boutique {shop.name} ({shop.owner.email})."
    )


def test_recharge_info_message_is_translated(shop_client, admin_whatsapp):
    response = shop_client.get(INFO, HTTP_ACCEPT_LANGUAGE="ar")

    text = unquote(response.json()["whatsapp_url"].split("?text=", 1)[1])
    assert shop_client.shop.name in text
    assert "Bonjour" not in text


def test_recharge_info_without_admin_contact_returns_empty_values(shop_client):
    body = shop_client.get(INFO).json()

    assert (body["admin_whatsapp"], body["whatsapp_url"], body["admin_contact_email"]) == (
        "",
        "",
        "",
    )


@pytest.mark.parametrize("url", [INFO, HISTORY])
@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", 403, "SHOP_STATE_FORBIDDEN"),
        ("ACTIVE", 200, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_recharge_endpoints_by_state(make_shop_client, url, state, expected_status, expected_code):
    response = make_shop_client(state).get(url)

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


def test_recharge_history_is_paginated_newest_first_without_admin_fields(
    shop_client, other_shop_client
):
    shop = shop_client.shop
    older = RechargeFactory(shop=shop, amount_received=1500, note="Paiement Bankily")
    newer = RechargeFactory(shop=shop, duration_months=12)
    RechargeFactory(shop=other_shop_client.shop)

    response = shop_client.get(HISTORY)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [item["id"] for item in body["results"]] == [newer.id, older.id]
    assert set(body["results"][0]) == {
        "id",
        "duration_months",
        "previous_expires_at",
        "new_expires_at",
        "created_at",
    }
    assert body["results"][0]["duration_months"] == 12


def test_recharge_history_page_out_of_range_returns_404(shop_client):
    response = shop_client.get(f"{HISTORY}?page=5")

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_recharge_history_query_count_is_constant(shop_client, django_assert_max_num_queries):
    RechargeFactory.create_batch(30, shop=shop_client.shop)

    with django_assert_max_num_queries(4):
        response = shop_client.get(f"{HISTORY}?page_size=30")

    assert len(response.json()["results"]) == 30
