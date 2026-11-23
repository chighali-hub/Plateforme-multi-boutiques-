"""Galerie des designs et onboarding (RG-05). Voir 03-reference-api.md section 5."""

import pytest

from apps.accounts.tests.helpers import error_code
from apps.core.models import AuditLog
from apps.notifications.models import Notification, NotificationType
from apps.shops.models import Shop, ThemeTemplate

pytestmark = pytest.mark.django_db
THEMES = "/api/v1/public/themes/"
DESIGN = "/api/v1/shop/onboarding/design/"
ACCEPT = "/api/v1/shop/onboarding/accept-terms/"


def _theme(code: str = "elegant") -> ThemeTemplate:
    return ThemeTemplate.objects.get(code=code)


# --- Galerie ----------------------------------------------------------------------
def test_themes_lists_active_templates_sorted_without_authentication(api_client):
    hidden = _theme("minimal")
    hidden.is_active = False
    hidden.save()

    response = api_client.get(THEMES)

    assert response.status_code == 200
    codes = [theme["code"] for theme in response.json()]
    assert codes == ["classique", "elegant", "moderne", "magazine", "tradition"]
    elegant = response.json()[1]
    assert set(elegant) == {
        "id",
        "code",
        "name",
        "name_fr",
        "name_ar",
        "layout",
        "preview_image_url",
        "default_primary_color",
        "default_accent_color",
    }
    assert elegant["name"] == "Élégant"
    assert elegant["preview_image_url"].startswith("http://testserver/media/themes/elegant")


def test_themes_name_follows_request_language(api_client):
    response = api_client.get(THEMES, HTTP_ACCEPT_LANGUAGE="ar")

    assert response.json()[1]["name"] == "أنيق"


def test_themes_ignore_an_invalid_token(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer jeton-perime")

    assert api_client.get(THEMES).status_code == 200


# --- Choix du design ---------------------------------------------------------------
def test_choose_design_saves_theme_and_moves_to_accept_terms(make_shop_client):
    client = make_shop_client("ONBOARDING")
    theme = _theme("elegant")

    response = client.post(
        DESIGN,
        {"theme_id": theme.id, "primary_color": "#7c2d5b", "accent_color": "#d4a52a"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_step"] == "ACCEPT_TERMS"
    assert body["state"] == "ONBOARDING"
    assert body["theme"]["code"] == "elegant"
    assert body["primary_color"] == "#7C2D5B"
    shop = Shop.objects.get(pk=client.shop.pk)
    assert (shop.theme_id, shop.primary_color, shop.accent_color) == (
        theme.id,
        "#7C2D5B",
        "#D4A52A",
    )


def test_choose_design_without_colors_uses_template_colors(make_shop_client):
    client = make_shop_client("ONBOARDING")
    theme = _theme("moderne")

    response = client.post(DESIGN, {"theme_id": theme.id}, format="json")

    assert response.status_code == 200
    assert response.json()["primary_color"] == theme.default_primary_color
    assert response.json()["accent_color"] == theme.default_accent_color


def test_choose_design_can_be_called_again_from_accept_terms(make_shop_client):
    client = make_shop_client("ONBOARDING", onboarding_step=Shop.OnboardingStep.ACCEPT_TERMS)

    response = client.post(DESIGN, {"theme_id": _theme("tradition").id}, format="json")

    assert response.status_code == 200
    assert response.json()["theme"]["code"] == "tradition"
    assert response.json()["onboarding_step"] == "ACCEPT_TERMS"


@pytest.mark.parametrize(
    "payload, field",
    [
        ({}, "theme_id"),
        ({"theme_id": 999999}, "theme_id"),
        ({"theme_id": "abc"}, "theme_id"),
        ({"theme_id": "THEME", "primary_color": "rouge"}, "primary_color"),
        ({"theme_id": "THEME", "accent_color": "#12345"}, "accent_color"),
    ],
)
def test_choose_design_rejects_invalid_payload(make_shop_client, payload, field):
    client = make_shop_client("ONBOARDING")
    payload = {key: (_theme().id if value == "THEME" else value) for key, value in payload.items()}

    response = client.post(DESIGN, payload, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert field in response.json()["error"]["details"]
    client.shop.refresh_from_db()
    assert client.shop.onboarding_step == Shop.OnboardingStep.CHOOSE_DESIGN


def test_choose_design_refuses_inactive_template(make_shop_client):
    client = make_shop_client("ONBOARDING")
    theme = _theme("magazine")
    theme.is_active = False
    theme.save()

    response = client.post(DESIGN, {"theme_id": theme.id}, format="json")

    assert response.status_code == 400
    assert "theme_id" in response.json()["error"]["details"]


def test_choose_design_before_email_verification_is_a_step_mismatch(make_shop_client):
    client = make_shop_client("ONBOARDING", onboarding_step=Shop.OnboardingStep.VERIFY_EMAIL)

    response = client.post(DESIGN, {"theme_id": _theme().id}, format="json")

    assert response.status_code == 409
    assert error_code(response) == "ONBOARDING_STEP_MISMATCH"
    assert response.json()["error"]["details"] == {"onboarding_step": "VERIFY_EMAIL"}


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 200, None),
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", 403, "SHOP_STATE_FORBIDDEN"),
        ("ACTIVE", 403, "SHOP_STATE_FORBIDDEN"),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_choose_design_by_state(make_shop_client, state, expected_status, expected_code):
    client = make_shop_client(state)

    response = client.post(DESIGN, {"theme_id": _theme().id}, format="json")

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


# --- Acceptation des conditions ----------------------------------------------------
def test_accept_terms_submits_shop_notifies_admins_and_audits(make_shop_client, admin_user):
    client = make_shop_client("ONBOARDING", onboarding_step=Shop.OnboardingStep.ACCEPT_TERMS)

    response = client.post(ACCEPT, {"accept_terms": True}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "PENDING"
    assert body["onboarding_step"] == "COMPLETED"
    assert body["submitted_at"] is not None
    shop = Shop.objects.get(pk=client.shop.pk)
    assert shop.terms_accepted_at is not None
    assert shop.submitted_at == shop.terms_accepted_at
    notification = Notification.objects.get(recipient=admin_user)
    assert notification.type == NotificationType.SHOP_SUBMITTED
    assert notification.data == {"shop_id": shop.pk, "shop_name": shop.name}
    audit = AuditLog.objects.get(action="SHOP_SUBMITTED")
    assert (audit.actor_id, audit.target_type, audit.target_id) == (
        shop.owner_id,
        "shop",
        shop.pk,
    )


@pytest.mark.parametrize("value", [False, "non", None])
def test_accept_terms_requires_true(make_shop_client, value):
    client = make_shop_client("ONBOARDING", onboarding_step=Shop.OnboardingStep.ACCEPT_TERMS)
    payload = {} if value is None else {"accept_terms": value}

    response = client.post(ACCEPT, payload, format="json")

    assert response.status_code == 400
    assert "accept_terms" in response.json()["error"]["details"]
    client.shop.refresh_from_db()
    assert client.shop.onboarding_step == Shop.OnboardingStep.ACCEPT_TERMS


def test_accept_terms_before_choosing_design_is_a_step_mismatch(make_shop_client, admin_user):
    client = make_shop_client("ONBOARDING")

    response = client.post(ACCEPT, {"accept_terms": True}, format="json")

    assert response.status_code == 409
    assert error_code(response) == "ONBOARDING_STEP_MISMATCH"
    assert response.json()["error"]["details"] == {"onboarding_step": "CHOOSE_DESIGN"}
    assert not Notification.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.parametrize(
    "state, expected_code",
    [
        ("PENDING", "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", "SHOP_STATE_FORBIDDEN"),
        ("ACTIVE", "SHOP_STATE_FORBIDDEN"),
        ("EXPIRED", "SHOP_EXPIRED"),
        ("BLOCKED", "SHOP_BLOCKED"),
    ],
)
def test_accept_terms_refused_outside_onboarding(make_shop_client, state, expected_code):
    client = make_shop_client(state)

    response = client.post(ACCEPT, {"accept_terms": True}, format="json")

    assert response.status_code == 403
    assert error_code(response) == expected_code


def test_full_onboarding_flow_ends_pending(make_shop_client):
    client = make_shop_client("ONBOARDING")

    client.post(DESIGN, {"theme_id": _theme().id}, format="json")
    response = client.post(ACCEPT, {"accept_terms": True}, format="json")

    assert response.json()["state"] == "PENDING"
    me = client.get("/api/v1/shop/me/").json()
    assert me["permissions"] == {
        "can_edit_profile": False,
        "can_edit_id_card": False,
        "can_resubmit": False,
        "can_manage_catalog": False,
        "can_manage_orders": False,
    }


@pytest.mark.parametrize("url", [DESIGN, ACCEPT])
def test_onboarding_requires_authentication(api_client, url):
    response = api_client.post(url, {}, format="json")

    assert response.status_code == 401
    assert error_code(response) == "AUTHENTICATION_REQUIRED"


@pytest.mark.parametrize("url", [DESIGN, ACCEPT])
def test_onboarding_refuses_admin(admin_client, url):
    response = admin_client.post(url, {}, format="json")

    assert response.status_code == 403
    assert error_code(response) == "PERMISSION_DENIED"
