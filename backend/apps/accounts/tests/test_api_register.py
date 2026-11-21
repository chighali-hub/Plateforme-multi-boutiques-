from pathlib import Path

import pytest
from django.conf import settings
from django.core import mail
from PIL import Image

from apps.accounts import services
from apps.accounts.models import OtpCode, User
from apps.accounts.tests.helpers import error_code
from apps.shops.models import Shop

pytestmark = pytest.mark.django_db
URL = "/api/v1/auth/shop/register/"


def _post(api_client, data, capture):
    with capture(execute=True):
        return api_client.post(URL, data, format="multipart")


def test_register_creates_unverified_account_and_shop(
    api_client, registration_data, django_capture_on_commit_callbacks
):
    response = _post(api_client, registration_data(), django_capture_on_commit_callbacks)

    assert response.status_code == 201
    assert response.json() == {
        "email": "aicha@example.com",
        "otp_expires_in": 600,
        "resend_available_in": 60,
    }
    user = User.objects.get(email="aicha@example.com")
    assert user.role == User.Role.SHOP and not user.is_email_verified
    assert user.check_password("MotDePasse!2026")
    shop = user.shop
    assert (shop.name, shop.slug, shop.phone, shop.whatsapp) == (
        "Aïcha Mode",
        "aicha-mode",
        "36123456",
        "46123456",
    )
    assert shop.onboarding_step == Shop.OnboardingStep.VERIFY_EMAIL
    assert shop.status == Shop.Status.PENDING
    assert shop.state == "ONBOARDING"


def test_register_sends_one_registration_code(
    api_client, registration_data, django_capture_on_commit_callbacks
):
    _post(api_client, registration_data(), django_capture_on_commit_callbacks)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["aicha@example.com"]
    otp = OtpCode.objects.get()
    assert otp.purpose == OtpCode.Purpose.REGISTRATION and otp.sent_to == "aicha@example.com"


def test_register_processes_logo_and_keeps_id_cards_private(
    api_client, registration_data, django_capture_on_commit_callbacks
):
    _post(api_client, registration_data(), django_capture_on_commit_callbacks)
    shop = Shop.objects.get()

    assert shop.logo.name.startswith("shops/logos/") and shop.logo.name.endswith(".webp")
    with Image.open(shop.logo.path) as logo:
        assert logo.format == "WEBP" and max(logo.size) == 512
    for card in (shop.id_card_front, shop.id_card_back):
        path = Path(card.path)
        assert card.name.startswith("id_cards/") and card.name.endswith(".jpg")
        assert path.is_relative_to(Path(settings.PRIVATE_MEDIA_ROOT))
        assert not path.is_relative_to(Path(settings.MEDIA_ROOT))
        assert "recto" not in card.name and "verso" not in card.name


@pytest.mark.parametrize(
    "field",
    [
        "shop_name",
        "logo",
        "description_fr",
        "description_ar",
        "address",
        "phone",
        "whatsapp",
        "email",
        "password",
        "password_confirm",
        "owner_full_name",
        "id_card_front",
        "id_card_back",
    ],
)
def test_register_requires_every_field(api_client, registration_data, field):
    response = api_client.post(URL, registration_data(**{field: None}), format="multipart")
    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert field in response.json()["error"]["details"]
    assert not User.objects.exists()


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"shop_name": "A"}, "shop_name"),
        ({"description_fr": "court"}, "description_fr"),
        ({"description_ar": "قصير"}, "description_ar"),
        ({"address": "Nkc"}, "address"),
        ({"phone": "12345678"}, "phone"),
        ({"whatsapp": "5612345"}, "whatsapp"),
        ({"email": "pas-un-email"}, "email"),
        ({"owner_full_name": "Al"}, "owner_full_name"),
        ({"password_confirm": "Autre!2026x"}, "password_confirm"),
    ],
)
def test_register_validates_fields(api_client, registration_data, overrides, field):
    response = api_client.post(URL, registration_data(**overrides), format="multipart")
    assert response.status_code == 400
    assert field in response.json()["error"]["details"]


@pytest.mark.parametrize(
    "password",
    ["Court1!", "12345678901", "password123", "aicha.example"],
    ids=["trop-court", "numerique", "courant", "proche-email"],
)
def test_register_enforces_password_policy(api_client, registration_data, password):
    data = registration_data(password=password, password_confirm=password)
    response = api_client.post(URL, data, format="multipart")
    assert response.status_code == 400
    assert "password" in response.json()["error"]["details"]


def test_register_rejects_fake_image(api_client, registration_data, fake_image_file):
    response = api_client.post(
        URL, registration_data(id_card_front=fake_image_file), format="multipart"
    )
    assert response.status_code == 400
    assert "id_card_front" in response.json()["error"]["details"]


def test_register_rejects_too_large_image(api_client, registration_data, settings):
    settings.UPLOAD_IMAGE_MAX_BYTES = 100
    response = api_client.post(URL, registration_data(), format="multipart")
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "FILE_TOO_LARGE"
    assert error["details"]["max_bytes"] == 100
    assert error["details"]["field"] in {"logo", "id_card_front", "id_card_back"}


@pytest.mark.parametrize("verified", [True, False])
def test_register_duplicate_email_ignoring_case(
    api_client, registration_data, verified, django_user_model
):
    django_user_model.objects.create_user(
        email="aicha@example.com", password="x", is_email_verified=verified
    )
    response = api_client.post(
        URL, registration_data(email="AICHA@EXAMPLE.COM"), format="multipart"
    )
    assert response.status_code == 409
    assert error_code(response) == "EMAIL_ALREADY_USED"
    assert response.json()["error"]["details"] == {"is_verified": verified}


def test_register_twice_same_name_gets_distinct_slugs(
    api_client, registration_data, django_capture_on_commit_callbacks
):
    _post(api_client, registration_data(), django_capture_on_commit_callbacks)
    _post(
        api_client, registration_data(email="autre@example.com"), django_capture_on_commit_callbacks
    )
    assert sorted(Shop.objects.values_list("slug", flat=True)) == ["aicha-mode", "aicha-mode-2"]


def test_register_failure_rolls_back_and_removes_files(
    api_client, registration_data, monkeypatch, settings
):
    def boom(*args, **kwargs):
        raise RuntimeError("panne du service OTP")

    monkeypatch.setattr(services.otp_service, "issue_otp", boom)
    response = api_client.post(URL, registration_data(), format="multipart")

    assert response.status_code == 500
    assert not User.objects.exists() and not Shop.objects.exists()
    for root in (settings.MEDIA_ROOT, settings.PRIVATE_MEDIA_ROOT):
        assert not [p for p in Path(root).rglob("*") if p.is_file()]


def test_register_ignores_bearer_token(api_client, registration_data):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer jeton-invalide")
    response = api_client.post(URL, registration_data(), format="multipart")
    assert response.status_code == 201


def test_register_email_follows_request_language(
    api_client, registration_data, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        api_client.post(URL, registration_data(), format="multipart", HTTP_ACCEPT_LANGUAGE="ar")
    message = mail.outbox[0]
    assert message.subject == "رمز التحقق الخاص بك"
    assert "رمز التحقق الخاص بك هو:" in message.body


def test_register_error_messages_follow_request_language(api_client, registration_data):
    response = api_client.post(
        URL, registration_data(phone="123"), format="multipart", HTTP_ACCEPT_LANGUAGE="ar"
    )
    assert response.json()["error"]["message"] == "البيانات المرسلة غير صالحة."
    assert response.json()["error"]["details"]["phone"] == [
        "أدخل رقمًا موريتانيًا من 8 أرقام يبدأ بـ 2 أو 3 أو 4."
    ]
