"""Profil, design, carte d'identite et renvoi de la demande (RG-13).

Voir 03-reference-api.md section 5.
"""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.tests.helpers import error_code
from apps.core.models import AuditLog
from apps.core.storage import private_storage
from apps.notifications.models import Notification, NotificationType
from apps.shops.models import Shop, ThemeTemplate
from apps.shops.tests.factories import BankAccountFactory

pytestmark = pytest.mark.django_db
ME = "/api/v1/shop/me/"
DESIGN = "/api/v1/shop/me/design/"
ID_CARD = "/api/v1/shop/me/id-card/"
RESUBMIT = "/api/v1/shop/me/resubmit/"

PROFILE_KEYS = {
    "id",
    "name",
    "slug",
    "email",
    "logo_url",
    "description_fr",
    "description_ar",
    "address",
    "phone",
    "whatsapp",
    "owner_full_name",
    "theme",
    "primary_color",
    "accent_color",
    "onboarding_step",
    "status",
    "state",
    "rejection_reason",
    "submitted_at",
    "approved_at",
    "expires_at",
    "days_left",
    "id_card_front_url",
    "id_card_back_url",
    "banks_count",
    "is_publicly_visible",
    "public_url",
    "permissions",
    "created_at",
}


def _store_private(name: str, content: bytes = b"carte") -> str:
    return private_storage().save(name, ContentFile(content))


# --- GET /shop/me/ ----------------------------------------------------------------
def test_get_profile_returns_complete_shop_profile(shop_client):
    shop = shop_client.shop

    response = shop_client.get(ME)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == PROFILE_KEYS
    assert body["email"] == shop.owner.email
    assert body["state"] == "ACTIVE"
    assert body["banks_count"] == 1
    assert body["is_publicly_visible"] is True
    assert body["public_url"] == f"http://localhost:5173/boutiques/{shop.slug}"
    assert body["id_card_front_url"] == "http://testserver/api/v1/shop/me/id-card/front/"
    assert body["id_card_back_url"] == "http://testserver/api/v1/shop/me/id-card/back/"
    assert body["logo_url"].startswith("http://testserver/media/shops/logos/")
    assert body["theme"]["code"] == "classique"
    assert body["permissions"] == {
        "can_edit_profile": True,
        "can_edit_id_card": False,
        "can_resubmit": False,
        "can_manage_catalog": True,
        "can_manage_orders": True,
    }


@override_settings(FRONTEND_URL="https://plateforme.mr/")
def test_public_url_uses_frontend_url(shop_client):
    assert shop_client.get(ME).json()["public_url"] == (
        f"https://plateforme.mr/boutiques/{shop_client.shop.slug}"
    )


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 200, None),
        ("PENDING", 200, None),
        ("REJECTED", 200, None),
        ("ACTIVE", 200, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_get_profile_by_state(make_shop_client, state, expected_status, expected_code):
    client = make_shop_client(state)

    response = client.get(ME)

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code
    else:
        assert response.json()["state"] == state


def test_expired_shop_error_carries_admin_whatsapp(make_shop_client, admin_whatsapp):
    client = make_shop_client("EXPIRED")

    response = client.get(ME)

    details = response.json()["error"]["details"]
    assert details["admin_whatsapp"] == admin_whatsapp
    assert details["whatsapp_url"].startswith(f"https://wa.me/222{admin_whatsapp}?text=")
    assert details["expired_at"] is not None


@pytest.mark.parametrize(
    "state, expected",
    [
        ("ONBOARDING", (False, False, False, False, False)),
        ("PENDING", (False, False, False, False, False)),
        ("REJECTED", (True, True, True, False, False)),
        ("ACTIVE", (True, False, False, True, True)),
    ],
)
def test_profile_permissions_follow_state_matrix(make_shop_client, state, expected):
    client = make_shop_client(state)

    permissions = client.get(ME).json()["permissions"]

    assert tuple(permissions.values()) == expected


def test_days_left_is_rounded_up_and_null_without_expiry(make_shop_client, freeze_now):
    now = freeze_now(timezone.now())
    client = make_shop_client("ACTIVE", expires_at=now + timedelta(days=2, hours=1))
    pending = make_shop_client("PENDING")

    assert client.get(ME).json()["days_left"] == 3
    assert pending.get(ME).json()["days_left"] is None


def test_active_shop_without_bank_is_not_publicly_visible(make_shop):
    shop = make_shop("ACTIVE")
    client = APIClient()
    client.force_authenticate(user=shop.owner)

    body = client.get(ME).json()

    assert body["banks_count"] == 0
    assert body["is_publicly_visible"] is False


def test_profile_requires_authentication(api_client):
    response = api_client.get(ME)

    assert response.status_code == 401
    assert error_code(response) == "AUTHENTICATION_REQUIRED"


def test_profile_refuses_admin(admin_client):
    response = admin_client.get(ME)

    assert response.status_code == 403
    assert error_code(response) == "PERMISSION_DENIED"


def test_get_profile_query_count_is_bounded(shop_client, django_assert_max_num_queries):
    with django_assert_max_num_queries(6):
        assert shop_client.get(ME).status_code == 200


# --- PATCH /shop/me/ ---------------------------------------------------------------
def test_patch_profile_updates_fields_and_search_texts_without_changing_slug(shop_client):
    shop = shop_client.shop
    slug = shop.slug

    response = shop_client.patch(
        ME,
        {
            "name": "  Aïcha Parfums  ",
            "description_fr": "Parfums et encens de qualité",
            "address": "Ksar, Nouakchott",
            "phone": "+222 22 11 33 44",
            "whatsapp": "00222 46 12 34 56",
            "owner_full_name": "Aicha Mint Ahmed",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Aïcha Parfums"
    assert body["slug"] == slug
    assert body["phone"] == "22113344"
    assert body["whatsapp"] == "46123456"
    shop.refresh_from_db()
    assert shop.slug == slug
    assert shop.search_name == "aicha parfums"
    assert "encens" in shop.search_text_fr
    assert shop.description_ar == "ملاحف و خمارات و عطور"


def test_patch_profile_replaces_logo_and_deletes_old_file(
    shop_client, image_file, django_capture_on_commit_callbacks
):
    shop = shop_client.shop
    shop.logo.save("ancien.webp", ContentFile(b"ancien"), save=True)
    old_name = shop.logo.name
    storage = shop.logo.storage

    with django_capture_on_commit_callbacks(execute=True):
        response = shop_client.patch(
            ME, {"logo": image_file("PNG", (1200, 900), name="nouveau.png")}, format="multipart"
        )

    assert response.status_code == 200
    shop.refresh_from_db()
    assert shop.logo.name != old_name
    assert shop.logo.name.startswith("shops/logos/") and shop.logo.name.endswith(".webp")
    assert storage.exists(shop.logo.name)
    assert not storage.exists(old_name)
    assert response.json()["logo_url"].endswith(shop.logo.name)


def test_patch_profile_rejects_fake_logo(shop_client, fake_image_file):
    response = shop_client.patch(ME, {"logo": fake_image_file}, format="multipart")

    assert response.status_code == 400
    assert "logo" in response.json()["error"]["details"]


@override_settings(UPLOAD_IMAGE_MAX_BYTES=100)
def test_patch_profile_rejects_too_large_logo(shop_client, image_file):
    response = shop_client.patch(ME, {"logo": image_file()}, format="multipart")

    assert response.status_code == 413
    assert error_code(response) == "FILE_TOO_LARGE"
    assert response.json()["error"]["details"]["field"] == "logo"


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "A"),
        ("name", "x" * 81),
        ("description_fr", "court"),
        ("description_ar", "x" * 501),
        ("address", "abc"),
        ("phone", "12345678"),
        ("whatsapp", "5612345"),
        ("owner_full_name", "Al"),
    ],
)
def test_patch_profile_validates_each_field(shop_client, field, value):
    before = Shop.objects.values(field).get(pk=shop_client.shop.pk)[field]

    response = shop_client.patch(ME, {field: value}, format="json")

    assert response.status_code == 400
    assert field in response.json()["error"]["details"]
    assert Shop.objects.values(field).get(pk=shop_client.shop.pk)[field] == before


def test_patch_profile_with_empty_body_changes_nothing(shop_client):
    response = shop_client.patch(ME, {}, format="json")

    assert response.status_code == 200
    assert response.json()["name"] == shop_client.shop.name


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
def test_patch_profile_by_state(make_shop_client, state, expected_status, expected_code):
    client = make_shop_client(state)

    response = client.patch(ME, {"address": "Ksar, Nouakchott"}, format="json")

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code
        assert response.json()["error"]["details"].get("state", state) == state
    client.shop.refresh_from_db()
    assert (client.shop.address == "Ksar, Nouakchott") is (expected_status == 200)


# --- PATCH /shop/me/design/ ----------------------------------------------------------
def test_patch_design_changes_template_and_colors(shop_client):
    theme = ThemeTemplate.objects.get(code="moderne")

    response = shop_client.patch(
        DESIGN, {"theme_id": theme.id, "primary_color": "#064e3b"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["theme"]["code"] == "moderne"
    assert body["primary_color"] == "#064E3B"
    assert body["accent_color"] == theme.default_accent_color
    shop_client.shop.refresh_from_db()
    assert shop_client.shop.theme_id == theme.id
    assert shop_client.shop.onboarding_step == Shop.OnboardingStep.COMPLETED


def test_patch_design_refuses_unknown_template(shop_client):
    response = shop_client.patch(DESIGN, {"theme_id": 424242}, format="json")

    assert response.status_code == 400
    assert "theme_id" in response.json()["error"]["details"]


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
def test_patch_design_by_state(make_shop_client, state, expected_status, expected_code):
    client = make_shop_client(state)
    theme = ThemeTemplate.objects.get(code="elegant")

    response = client.patch(DESIGN, {"theme_id": theme.id}, format="json")

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


# --- Carte d'identite ----------------------------------------------------------------
def test_rejected_shop_replaces_one_id_card_side(
    make_shop_client, image_file, django_capture_on_commit_callbacks
):
    client = make_shop_client("REJECTED")
    shop = client.shop
    old_front = _store_private("id_cards/2026/01/ancien-recto.jpg")
    old_back = _store_private("id_cards/2026/01/ancien-verso.jpg")
    Shop.objects.filter(pk=shop.pk).update(id_card_front=old_front, id_card_back=old_back)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.put(
            ID_CARD, {"id_card_front": image_file("JPEG", (1200, 800))}, format="multipart"
        )

    assert response.status_code == 200
    shop.refresh_from_db()
    storage = private_storage()
    assert shop.id_card_front.name != old_front
    assert shop.id_card_front.name.startswith("id_cards/")
    assert storage.exists(shop.id_card_front.name)
    assert not storage.exists(old_front)
    assert shop.id_card_back.name == old_back
    assert storage.exists(old_back)


def test_id_card_is_stored_privately_outside_media(make_shop_client, image_file, settings):
    client = make_shop_client("REJECTED")

    client.put(
        ID_CARD,
        {"id_card_front": image_file(), "id_card_back": image_file("PNG")},
        format="multipart",
    )

    client.shop.refresh_from_db()
    for field_file in (client.shop.id_card_front, client.shop.id_card_back):
        path = settings.PRIVATE_MEDIA_ROOT / field_file.name
        assert path.exists()
        assert not (settings.MEDIA_ROOT / field_file.name).exists()
        with pytest.raises(ValueError):
            field_file.url  # noqa: B018 - un fichier prive n'a pas d'URL


def test_id_card_update_requires_at_least_one_side(make_shop_client):
    client = make_shop_client("REJECTED")

    response = client.put(ID_CARD, {}, format="multipart")

    assert response.status_code == 400
    assert "non_field_errors" in response.json()["error"]["details"]


def test_id_card_update_rejects_fake_image(make_shop_client, fake_image_file):
    client = make_shop_client("REJECTED")

    response = client.put(ID_CARD, {"id_card_back": fake_image_file}, format="multipart")

    assert response.status_code == 400
    assert "id_card_back" in response.json()["error"]["details"]


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", 200, None),
        ("ACTIVE", 403, "SHOP_STATE_FORBIDDEN"),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_id_card_update_by_state(
    make_shop_client, image_file, state, expected_status, expected_code
):
    client = make_shop_client(state)

    response = client.put(ID_CARD, {"id_card_front": image_file()}, format="multipart")

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


@pytest.mark.parametrize("side, field", [("front", "id_card_front"), ("back", "id_card_back")])
def test_read_own_id_card_returns_private_file(make_shop_client, side, field):
    client = make_shop_client("PENDING")
    name = _store_private(f"id_cards/2026/01/{side}.jpg", b"contenu-" + side.encode())
    Shop.objects.filter(pk=client.shop.pk).update(**{field: name})

    response = client.get(f"{ID_CARD}{side}/")

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"contenu-" + side.encode()
    assert response["Content-Type"] == "image/jpeg"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_read_id_card_unknown_side_returns_404(make_shop_client):
    response = make_shop_client("ACTIVE").get(f"{ID_CARD}middle/")

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_read_id_card_missing_file_returns_404(make_shop_client):
    response = make_shop_client("ACTIVE").get(f"{ID_CARD}front/")

    assert response.status_code == 404


def test_read_id_card_only_returns_own_card(make_shop_client):
    owner = make_shop_client("ACTIVE")
    other = make_shop_client("ACTIVE")
    secret = _store_private("id_cards/2026/01/secret.jpg", b"secret-du-proprietaire")
    Shop.objects.filter(pk=owner.shop.pk).update(id_card_front=secret)

    response = other.get(f"{ID_CARD}front/")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 200, None),
        ("REJECTED", 200, None),
        ("ACTIVE", 200, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_read_id_card_by_state(make_shop_client, state, expected_status, expected_code):
    client = make_shop_client(state)
    name = _store_private("id_cards/2026/01/recto.jpg")
    Shop.objects.filter(pk=client.shop.pk).update(id_card_front=name)

    response = client.get(f"{ID_CARD}front/")

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


def test_read_id_card_refuses_anonymous_and_admin(api_client, admin_client):
    assert api_client.get(f"{ID_CARD}front/").status_code == 401
    assert admin_client.get(f"{ID_CARD}front/").status_code == 403


# --- Renvoi de la demande (RG-13) ---------------------------------------------------
def test_rejected_shop_edits_profile_then_resubmits(make_shop_client, admin_user, image_file):
    client = make_shop_client("REJECTED")
    shop = client.shop
    reason = shop.rejection_reason

    assert client.patch(ME, {"address": "Ksar, Nouakchott"}, format="json").status_code == 200
    assert (
        client.put(ID_CARD, {"id_card_front": image_file()}, format="multipart").status_code == 200
    )
    response = client.post(RESUBMIT)

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "PENDING"
    assert body["status"] == "PENDING"
    assert body["rejection_reason"] == reason
    shop.refresh_from_db()
    assert shop.status == Shop.Status.PENDING
    assert shop.submitted_at > shop.rejected_at
    notification = Notification.objects.get(recipient=admin_user)
    assert notification.type == NotificationType.SHOP_RESUBMITTED
    assert notification.data == {"shop_id": shop.pk, "shop_name": shop.name}
    audit = AuditLog.objects.get(action="SHOP_RESUBMITTED")
    assert audit.target_id == shop.pk
    assert audit.metadata == {"previous_rejection_reason": reason}


def test_resubmit_twice_is_refused(make_shop_client):
    client = make_shop_client("REJECTED")
    client.post(RESUBMIT)

    response = client.post(RESUBMIT)

    assert response.status_code == 403
    assert error_code(response) == "SHOP_STATE_FORBIDDEN"
    assert AuditLog.objects.filter(action="SHOP_RESUBMITTED").count() == 1


@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", 200, None),
        ("ACTIVE", 403, "SHOP_STATE_FORBIDDEN"),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_resubmit_by_state(make_shop_client, state, expected_status, expected_code):
    client = make_shop_client(state)

    response = client.post(RESUBMIT)

    assert response.status_code == expected_status
    if expected_code:
        assert error_code(response) == expected_code


def test_profile_shows_visibility_after_bank_changes(make_shop):
    shop = make_shop("ACTIVE")
    client = APIClient()
    client.force_authenticate(user=shop.owner)
    assert client.get(ME).json()["is_publicly_visible"] is False

    BankAccountFactory(shop=shop)

    assert client.get(ME).json()["is_publicly_visible"] is True
