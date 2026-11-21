from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import DEFAULT_PASSWORD, AdminUserFactory, UserFactory
from apps.accounts.tests.helpers import error_code
from apps.core.models import AuditLog
from apps.shops.tests.factories import ShopFactory

pytestmark = pytest.mark.django_db
SHOP_LOGIN = "/api/v1/auth/shop/login/"
ADMIN_LOGIN = "/api/v1/auth/admin/login/"


def _login(api_client, url, email, password=DEFAULT_PASSWORD):
    return api_client.post(url, {"email": email, "password": password})


@pytest.mark.parametrize("state", ["ONBOARDING", "PENDING", "REJECTED", "ACTIVE"])
def test_shop_login_returns_tokens_for_allowed_states(api_client, make_shop, state):
    shop = make_shop(state)
    response = _login(api_client, SHOP_LOGIN, shop.owner.email)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access", "refresh", "user"}
    assert body["user"]["role"] == "SHOP"
    assert body["user"]["shop"]["id"] == shop.id
    assert body["user"]["shop"]["state"] == state


def test_shop_login_email_is_case_insensitive(api_client, make_shop):
    shop = make_shop("ACTIVE")
    assert _login(api_client, SHOP_LOGIN, shop.owner.email.upper()).status_code == 200


def test_shop_login_updates_last_login(api_client, make_shop):
    shop = make_shop("ACTIVE")
    _login(api_client, SHOP_LOGIN, shop.owner.email)
    shop.owner.refresh_from_db()
    assert shop.owner.last_login is not None


@pytest.mark.parametrize(
    "email, password",
    [("inconnu@example.com", DEFAULT_PASSWORD), (None, "MauvaisMotDePasse!1")],
    ids=["email-inconnu", "mot-de-passe-faux"],
)
def test_shop_login_invalid_credentials_same_error(api_client, make_shop, email, password):
    shop = make_shop("ACTIVE")
    response = _login(api_client, SHOP_LOGIN, email or shop.owner.email, password)
    assert response.status_code == 401
    assert error_code(response) == "INVALID_CREDENTIALS"
    assert response.json()["error"]["details"] == {}


def test_shop_login_unverified_email(api_client):
    shop = ShopFactory(owner=UserFactory(is_email_verified=False), onboarding_step="VERIFY_EMAIL")
    response = _login(api_client, SHOP_LOGIN, shop.owner.email)
    assert response.status_code == 403
    assert error_code(response) == "EMAIL_NOT_VERIFIED"
    assert response.json()["error"]["details"] == {"email": shop.owner.email}


def test_shop_login_wrong_password_checked_before_verification(api_client):
    shop = ShopFactory(owner=UserFactory(is_email_verified=False))
    response = _login(api_client, SHOP_LOGIN, shop.owner.email, "MauvaisMotDePasse!1")
    assert error_code(response) == "INVALID_CREDENTIALS"


def test_shop_login_blocked(api_client, make_shop, admin_whatsapp):
    shop = make_shop("BLOCKED")
    response = _login(api_client, SHOP_LOGIN, shop.owner.email)
    assert response.status_code == 403
    assert error_code(response) == "SHOP_BLOCKED"
    assert response.json()["error"]["details"]["admin_whatsapp"] == "22334455"


def test_shop_login_expired_gives_whatsapp_link(api_client, make_shop, admin_whatsapp):
    shop = make_shop("EXPIRED", name="Aicha Mode")
    response = _login(api_client, SHOP_LOGIN, shop.owner.email)
    assert response.status_code == 403
    assert error_code(response) == "SHOP_EXPIRED"
    details = response.json()["error"]["details"]
    assert details["expired_at"] == shop.expires_at.isoformat()
    assert details["whatsapp_url"].startswith("https://wa.me/22222334455?text=Bonjour")


def test_shop_login_blocked_checked_before_expired(api_client, make_shop):
    shop = make_shop("BLOCKED", expires_at=timezone.now() - timedelta(days=1))
    assert error_code(_login(api_client, SHOP_LOGIN, shop.owner.email)) == "SHOP_BLOCKED"


def test_admin_cannot_use_shop_login(api_client):
    admin = AdminUserFactory()
    response = _login(api_client, SHOP_LOGIN, admin.email)
    assert response.status_code == 401 and error_code(response) == "INVALID_CREDENTIALS"


def test_shop_cannot_use_admin_login(api_client, make_shop):
    shop = make_shop("ACTIVE")
    response = _login(api_client, ADMIN_LOGIN, shop.owner.email)
    assert response.status_code == 401 and error_code(response) == "INVALID_CREDENTIALS"
    assert not AuditLog.objects.exists()


def test_admin_login_returns_tokens_and_audits(api_client):
    admin = AdminUserFactory()
    response = api_client.post(
        ADMIN_LOGIN,
        {"email": admin.email, "password": DEFAULT_PASSWORD},
        REMOTE_ADDR="197.231.1.10",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "ADMIN" and body["user"]["shop"] is None
    entry = AuditLog.objects.get()
    assert (entry.action, entry.actor, entry.ip_address) == (
        "ADMIN_LOGIN",
        admin,
        "197.231.1.10",
    )


def test_admin_login_wrong_password(api_client):
    admin = AdminUserFactory()
    response = _login(api_client, ADMIN_LOGIN, admin.email, "MauvaisMotDePasse!1")
    assert response.status_code == 401 and error_code(response) == "INVALID_CREDENTIALS"
    assert not AuditLog.objects.exists()


def test_inactive_account_cannot_log_in(api_client, make_shop):
    shop = make_shop("ACTIVE")
    shop.owner.is_active = False
    shop.owner.save()
    assert error_code(_login(api_client, SHOP_LOGIN, shop.owner.email)) == "INVALID_CREDENTIALS"


def test_login_validates_payload(api_client):
    response = api_client.post(SHOP_LOGIN, {"email": "pas-un-email"})
    assert response.status_code == 400
    assert set(response.json()["error"]["details"]) == {"email", "password"}
