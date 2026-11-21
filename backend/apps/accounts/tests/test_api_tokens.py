from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.tests.factories import DEFAULT_PASSWORD
from apps.accounts.tests.helpers import error_code
from apps.accounts.tokens import issue_tokens, revoke_all_sessions
from apps.shops.models import Shop

pytestmark = pytest.mark.django_db
REFRESH = "/api/v1/auth/token/refresh/"
LOGOUT = "/api/v1/auth/logout/"
ME = "/api/v1/auth/me/"


def _bearer(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def test_access_token_carries_user_id_and_role(make_shop):
    shop = make_shop("ACTIVE")
    access = AccessToken(issue_tokens(shop.owner)["access"])
    assert (str(access["user_id"]), access["role"]) == (str(shop.owner.pk), "SHOP")
    assert "state" not in access.payload


def test_access_token_lifetime_is_15_minutes(make_shop):
    access = AccessToken(issue_tokens(make_shop("ACTIVE").owner)["access"])
    assert access["exp"] - access["iat"] == 15 * 60


def test_refresh_rotates_and_revokes_old_token(api_client, make_shop):
    tokens = issue_tokens(make_shop("ACTIVE").owner)

    response = api_client.post(REFRESH, {"refresh": tokens["refresh"]})

    assert response.status_code == 200
    new = response.json()
    assert set(new) == {"access", "refresh"} and new["refresh"] != tokens["refresh"]
    again = api_client.post(REFRESH, {"refresh": tokens["refresh"]})
    assert again.status_code == 401 and error_code(again) == "TOKEN_INVALID"
    assert api_client.post(REFRESH, {"refresh": new["refresh"]}).status_code == 200


@pytest.mark.parametrize("raw", ["n-importe-quoi", ""])
def test_refresh_invalid_token(api_client, raw):
    response = api_client.post(REFRESH, {"refresh": raw})
    assert response.status_code in (400, 401)
    assert error_code(response) in ("TOKEN_INVALID", "VALIDATION_ERROR")


def test_refresh_rejects_access_token(api_client, make_shop):
    tokens = issue_tokens(make_shop("ACTIVE").owner)
    response = api_client.post(REFRESH, {"refresh": tokens["access"]})
    assert response.status_code == 401 and error_code(response) == "TOKEN_INVALID"


@pytest.mark.parametrize("state, code", [("BLOCKED", "SHOP_BLOCKED"), ("EXPIRED", "SHOP_EXPIRED")])
def test_refresh_refused_for_blocked_or_expired_shop(api_client, make_shop, state, code):
    shop = make_shop("ACTIVE")
    tokens = issue_tokens(shop.owner)
    if state == "BLOCKED":
        Shop.objects.filter(pk=shop.pk).update(is_blocked=True)
    else:
        Shop.objects.filter(pk=shop.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

    response = api_client.post(REFRESH, {"refresh": tokens["refresh"]})

    assert response.status_code == 403 and error_code(response) == code
    # Le jeton n'a pas ete consomme : apres deblocage ou recharge, il reste utilisable.
    Shop.objects.filter(pk=shop.pk).update(
        is_blocked=False, expires_at=timezone.now() + timedelta(days=30)
    )
    assert api_client.post(REFRESH, {"refresh": tokens["refresh"]}).status_code == 200


def test_refresh_refused_for_inactive_user(api_client, make_shop):
    shop = make_shop("ACTIVE")
    tokens = issue_tokens(shop.owner)
    shop.owner.is_active = False
    shop.owner.save()
    assert error_code(api_client.post(REFRESH, {"refresh": tokens["refresh"]})) == "TOKEN_INVALID"


def test_logout_blacklists_refresh(api_client, make_shop):
    tokens = issue_tokens(make_shop("ACTIVE").owner)
    response = api_client.post(LOGOUT, {"refresh": tokens["refresh"]}, **_bearer(tokens["access"]))
    assert response.status_code == 204
    assert error_code(api_client.post(REFRESH, {"refresh": tokens["refresh"]})) == "TOKEN_INVALID"


def test_logout_requires_authentication(api_client, make_shop):
    tokens = issue_tokens(make_shop("ACTIVE").owner)
    response = api_client.post(LOGOUT, {"refresh": tokens["refresh"]})
    assert response.status_code == 401 and error_code(response) == "AUTHENTICATION_REQUIRED"


def test_logout_cannot_revoke_someone_elses_token(api_client, make_shop):
    mine = issue_tokens(make_shop("ACTIVE").owner)
    theirs = issue_tokens(make_shop("ACTIVE").owner)
    response = api_client.post(LOGOUT, {"refresh": theirs["refresh"]}, **_bearer(mine["access"]))
    assert response.status_code == 401 and error_code(response) == "TOKEN_INVALID"
    assert api_client.post(REFRESH, {"refresh": theirs["refresh"]}).status_code == 200


def test_revoke_all_sessions_closes_every_refresh(api_client, make_shop):
    owner = make_shop("ACTIVE").owner
    sessions = [issue_tokens(owner) for _ in range(3)]
    assert revoke_all_sessions(owner) == 3
    for tokens in sessions:
        assert api_client.post(REFRESH, {"refresh": tokens["refresh"]}).status_code == 401


def test_me_returns_user_object(api_client, make_shop):
    shop = make_shop("PENDING")
    tokens = issue_tokens(shop.owner)
    body = api_client.get(ME, **_bearer(tokens["access"])).json()
    assert body == {
        "id": shop.owner.id,
        "email": shop.owner.email,
        "role": "SHOP",
        "is_email_verified": True,
        "shop": {
            "id": shop.id,
            "name": shop.name,
            "slug": shop.slug,
            "logo_url": f"http://testserver/media/{shop.logo.name}",
            "state": "PENDING",
            "onboarding_step": "COMPLETED",
            "expires_at": None,
        },
    }


def test_me_for_admin_has_no_shop(admin_client):
    assert admin_client.get(ME).json()["shop"] is None


@pytest.mark.parametrize(
    "state, expected",
    [
        ("ONBOARDING", 200),
        ("PENDING", 200),
        ("REJECTED", 200),
        ("ACTIVE", 200),
        ("EXPIRED", 403),
        ("BLOCKED", 403),
    ],
)
def test_me_state_matrix(make_shop_client, state, expected):
    assert make_shop_client(state).get(ME).status_code == expected


def test_me_requires_authentication(api_client):
    response = api_client.get(ME)
    assert response.status_code == 401 and error_code(response) == "AUTHENTICATION_REQUIRED"


def test_me_with_garbage_token(api_client):
    response = api_client.get(ME, HTTP_AUTHORIZATION="Bearer abc.def.ghi")
    assert response.status_code == 401 and error_code(response) == "TOKEN_INVALID"


def test_password_unused_in_token_payload(make_shop):
    access = AccessToken(issue_tokens(make_shop("ACTIVE").owner)["access"])
    assert DEFAULT_PASSWORD not in str(access.payload)


def test_refresh_race_window_is_closed_by_row_lock(api_client, make_shop, monkeypatch):
    """Deux rafraichissements simultanes passent tous deux le pre-controle de
    simplejwt avant toute revocation. On simule cette fenetre en neutralisant
    ce pre-controle : seul le controle sous verrou doit alors refuser le second."""
    tokens = issue_tokens(make_shop("ACTIVE").owner)
    monkeypatch.setattr(RefreshToken, "check_blacklist", lambda self: None)

    first = api_client.post(REFRESH, {"refresh": tokens["refresh"]})
    second = api_client.post(REFRESH, {"refresh": tokens["refresh"]})

    assert first.status_code == 200
    assert second.status_code == 401 and error_code(second) == "TOKEN_INVALID"
