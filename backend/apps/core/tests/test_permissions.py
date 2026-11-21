from datetime import timedelta

import pytest
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import PlatformSettings
from apps.core.permissions import IsPlatformAdmin, IsShopOwner, ShopStateAllowed

ALL_LIVE_STATES = ("ONBOARDING", "PENDING", "REJECTED", "ACTIVE")


class AdminOnlyView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return Response({"ok": True})


class ShopAnyStateView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(*ALL_LIVE_STATES)]

    def get(self, request):
        return Response({"shop_id": request.shop.id})


class ShopWriteView(APIView):
    def get_permissions(self):
        return [IsShopOwner(), ShopStateAllowed("REJECTED", "ACTIVE")]

    def get(self, request):
        return Response({"shop_id": request.shop.id})


urlpatterns = [
    path("t/admin/", AdminOnlyView.as_view()),
    path("t/shop/", ShopAnyStateView.as_view()),
    path("t/shop-write/", ShopWriteView.as_view()),
]

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]


def _code(response):
    return response.json()["error"]["code"]


def test_admin_endpoint_requires_authentication(api_client):
    response = api_client.get("/t/admin/")
    assert response.status_code == 401
    assert _code(response) == "AUTHENTICATION_REQUIRED"


def test_admin_endpoint_accepts_admin(admin_client):
    assert admin_client.get("/t/admin/").status_code == 200


def test_admin_endpoint_rejects_shop_owner(shop_client):
    response = shop_client.get("/t/admin/")
    assert response.status_code == 403
    assert _code(response) == "PERMISSION_DENIED"


def test_shop_endpoint_rejects_admin(admin_client):
    response = admin_client.get("/t/shop/")
    assert response.status_code == 403
    assert _code(response) == "PERMISSION_DENIED"


def test_shop_endpoint_requires_authentication(api_client):
    assert _code(api_client.get("/t/shop/")) == "AUTHENTICATION_REQUIRED"


def test_shop_endpoint_exposes_own_shop_only(shop_client, other_shop_client):
    assert shop_client.get("/t/shop/").json() == {"shop_id": shop_client.shop.id}
    assert other_shop_client.get("/t/shop/").json() == {"shop_id": other_shop_client.shop.id}


def test_shop_role_without_shop_is_denied(api_client, django_user_model):
    user = django_user_model.objects.create_user(email="sans@boutique.mr", password="x")
    api_client.force_authenticate(user=user)
    assert _code(api_client.get("/t/shop/")) == "PERMISSION_DENIED"


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", 200, None),
        ("ACTIVE", 200, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_shop_state_matrix(make_shop_client, state, expected_status, expected_code):
    response = make_shop_client(state).get("/t/shop-write/")
    assert response.status_code == expected_status
    if expected_code:
        assert _code(response) == expected_code


def test_state_forbidden_reports_current_state(make_shop_client):
    response = make_shop_client("PENDING").get("/t/shop-write/")
    assert response.json()["error"]["details"] == {"state": "PENDING"}


def test_blocked_wins_over_expired(make_shop_client):
    client = make_shop_client("BLOCKED", expires_at=timezone.now() - timedelta(days=3))
    assert _code(client.get("/t/shop/")) == "SHOP_BLOCKED"


def test_expired_details_contain_admin_whatsapp_link(make_shop_client):
    settings_row = PlatformSettings.load()
    settings_row.admin_whatsapp = "22334455"
    settings_row.save()
    client = make_shop_client("EXPIRED", name="Aicha Mode")

    details = client.get("/t/shop/").json()["error"]["details"]

    assert details["expired_at"] == client.shop.expires_at.isoformat()
    assert details["admin_whatsapp"] == "22334455"
    assert details["whatsapp_url"].startswith("https://wa.me/22222334455?text=Bonjour")
    assert "Aicha%20Mode" in details["whatsapp_url"]


def test_blocked_details_contain_admin_contact(make_shop_client):
    settings_row = PlatformSettings.load()
    settings_row.admin_whatsapp = "22334455"
    settings_row.save()
    details = make_shop_client("BLOCKED").get("/t/shop/").json()["error"]["details"]
    assert details == {"admin_whatsapp": "22334455", "whatsapp_url": "https://wa.me/22222334455"}


def test_state_is_checked_on_every_request(shop_client):
    assert shop_client.get("/t/shop/").status_code == 200
    shop = shop_client.shop
    shop.expires_at = timezone.now() - timedelta(seconds=1)
    shop.save(update_fields=["expires_at"])
    assert _code(shop_client.get("/t/shop/")) == "SHOP_EXPIRED"


def test_shop_state_allowed_rejects_unknown_states():
    with pytest.raises(ValueError):
        ShopStateAllowed("ACTIVE", "ARCHIVED")
    with pytest.raises(ValueError):
        ShopStateAllowed()
