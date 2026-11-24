"""Tous les endpoints /admin/ sont reserves a role = ADMIN."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.helpers import error_code
from apps.administration.models import Recharge
from apps.catalog.models import Product
from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db


def _endpoints(shop_id: int, product_id: int) -> list[tuple[str, str]]:
    base = f"/api/v1/admin/shops/{shop_id}"
    return [
        ("get", "/api/v1/admin/dashboard/"),
        ("get", "/api/v1/admin/shops/"),
        ("get", f"{base}/"),
        ("get", f"{base}/id-card/front/"),
        ("post", f"{base}/approve/"),
        ("post", f"{base}/reject/"),
        ("post", f"{base}/block/"),
        ("post", f"{base}/unblock/"),
        ("get", f"{base}/recharge-preview/?duration_months=1"),
        ("post", f"{base}/recharge/"),
        ("get", f"{base}/recharges/"),
        ("get", f"{base}/products/"),
        ("post", f"{base}/products/{product_id}/remove/"),
        ("get", "/api/v1/admin/recharges/"),
        ("get", "/api/v1/admin/settings/"),
        ("patch", "/api/v1/admin/settings/"),
        ("get", "/api/v1/admin/audit-logs/"),
    ]


@pytest.fixture
def target(make_shop):
    shop = make_shop("PENDING")
    return shop, ProductFactory(shop=shop)


@pytest.mark.parametrize("state", ["ONBOARDING", "PENDING", "REJECTED", "ACTIVE"])
def test_shop_user_gets_403_on_every_admin_endpoint(make_shop_client, target, state):
    client = make_shop_client(state)
    shop, product = target

    for method, url in _endpoints(shop.pk, product.pk):
        response = getattr(client, method)(url, {"reason": "Motif tres valable."}, format="json")
        assert response.status_code == 403, (method, url)
        assert error_code(response) == "PERMISSION_DENIED", (method, url)

    shop.refresh_from_db()
    assert shop.status == "PENDING"
    assert Product.objects.filter(pk=product.pk).exists()
    assert not Recharge.objects.exists() and not AuditLog.objects.exists()


def test_anonymous_gets_401_on_every_admin_endpoint(target):
    client = APIClient()
    shop, product = target

    for method, url in _endpoints(shop.pk, product.pk):
        response = getattr(client, method)(url, {}, format="json")
        assert response.status_code == 401, (method, url)
        assert error_code(response) == "AUTHENTICATION_REQUIRED", (method, url)


def test_invalid_token_gets_401_token_invalid():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer jeton-invalide")

    response = client.get("/api/v1/admin/dashboard/")

    assert response.status_code == 401 and error_code(response) == "TOKEN_INVALID"
