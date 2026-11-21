from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import OtpCode, User
from apps.accounts.tests.factories import UserFactory
from apps.accounts.tests.helpers import error_code, last_code_sent_to
from apps.shops.models import Shop
from apps.shops.tests.factories import ShopFactory

pytestmark = pytest.mark.django_db
REGISTER = "/api/v1/auth/shop/register/"
VERIFY = "/api/v1/auth/shop/verify-email/"
RESEND = "/api/v1/auth/otp/resend/"
EMAIL = "aicha@example.com"


@pytest.fixture
def registered(api_client, registration_data, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        api_client.post(REGISTER, registration_data(), format="multipart")
    return User.objects.get(email=EMAIL)


def _wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def test_full_registration_flow_returns_tokens(api_client, registered):
    response = api_client.post(VERIFY, {"email": EMAIL, "code": last_code_sent_to(EMAIL)})

    assert response.status_code == 200
    body = response.json()
    assert body["access"] and body["refresh"]
    assert body["user"]["email"] == EMAIL and body["user"]["is_email_verified"] is True
    assert body["user"]["shop"]["state"] == "ONBOARDING"
    assert body["user"]["shop"]["onboarding_step"] == "CHOOSE_DESIGN"
    assert body["user"]["shop"]["logo_url"].startswith("http://testserver/media/shops/logos/")
    registered.refresh_from_db()
    assert registered.is_email_verified
    assert registered.shop.onboarding_step == Shop.OnboardingStep.CHOOSE_DESIGN

    me = api_client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {body['access']}")
    assert me.status_code == 200 and me.json()["email"] == EMAIL


def test_verify_email_is_case_insensitive(api_client, registered):
    response = api_client.post(
        VERIFY, {"email": "AICHA@example.COM", "code": last_code_sent_to(EMAIL)}
    )
    assert response.status_code == 200


def test_verify_wrong_code_reports_attempts_left(api_client, registered):
    code = last_code_sent_to(EMAIL)
    response = api_client.post(VERIFY, {"email": EMAIL, "code": _wrong(code)})
    assert response.status_code == 400
    assert error_code(response) == "OTP_INVALID"
    assert response.json()["error"]["details"] == {"attempts_left": 4}


def test_verify_five_wrong_codes_lock_the_code(api_client, registered):
    code = last_code_sent_to(EMAIL)
    codes = [api_client.post(VERIFY, {"email": EMAIL, "code": _wrong(code)}) for _ in range(5)]
    assert [error_code(r) for r in codes] == ["OTP_INVALID"] * 4 + ["OTP_TOO_MANY_ATTEMPTS"]
    response = api_client.post(VERIFY, {"email": EMAIL, "code": code})
    assert error_code(response) == "OTP_TOO_MANY_ATTEMPTS"
    registered.refresh_from_db()
    assert not registered.is_email_verified


def test_verify_expired_code(api_client, registered):
    OtpCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = api_client.post(VERIFY, {"email": EMAIL, "code": last_code_sent_to(EMAIL)})
    assert response.status_code == 400 and error_code(response) == "OTP_EXPIRED"


def test_verify_code_cannot_be_reused(api_client, registered):
    code = last_code_sent_to(EMAIL)
    api_client.post(VERIFY, {"email": EMAIL, "code": code})
    User.objects.filter(email=EMAIL).update(is_email_verified=False)
    response = api_client.post(VERIFY, {"email": EMAIL, "code": code})
    assert error_code(response) == "OTP_EXPIRED"


def test_verify_unknown_email_does_not_disclose(api_client):
    response = api_client.post(VERIFY, {"email": "inconnu@example.com", "code": "123456"})
    assert response.status_code == 400 and error_code(response) == "OTP_EXPIRED"


def test_verify_already_verified(api_client, registered):
    code = last_code_sent_to(EMAIL)
    api_client.post(VERIFY, {"email": EMAIL, "code": code})
    response = api_client.post(VERIFY, {"email": EMAIL, "code": code})
    assert response.status_code == 409 and error_code(response) == "ALREADY_VERIFIED"


@pytest.mark.parametrize("code", ["12345", "1234567", "12a456", ""])
def test_verify_code_format(api_client, code):
    response = api_client.post(VERIFY, {"email": EMAIL, "code": code})
    assert response.status_code == 400 and error_code(response) == "VALIDATION_ERROR"
    assert "code" in response.json()["error"]["details"]


def test_resend_registration_too_soon(api_client, registered):
    response = api_client.post(RESEND, {"email": EMAIL, "purpose": "REGISTRATION"})
    assert response.status_code == 429
    assert error_code(response) == "OTP_RESEND_TOO_SOON"
    assert 0 < response.json()["error"]["details"]["retry_after"] <= 60


def test_resend_registration_after_delay_invalidates_old_code(
    api_client, registered, django_capture_on_commit_callbacks
):
    old_code = last_code_sent_to(EMAIL)
    OtpCode.objects.update(created_at=timezone.now() - timedelta(seconds=61))
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(RESEND, {"email": EMAIL, "purpose": "REGISTRATION"})
    assert response.status_code == 200
    assert response.json() == {"resend_available_in": 60}
    assert len(mail.outbox) == 2
    new_code = last_code_sent_to(EMAIL)
    if new_code != old_code:
        assert error_code(api_client.post(VERIFY, {"email": EMAIL, "code": old_code})) == (
            "OTP_INVALID"
        )
    assert api_client.post(VERIFY, {"email": EMAIL, "code": new_code}).status_code == 200


@pytest.mark.parametrize("purpose", ["REGISTRATION", "PASSWORD_RESET"])
def test_resend_unknown_email_same_response(api_client, purpose):
    response = api_client.post(RESEND, {"email": "inconnu@example.com", "purpose": purpose})
    assert response.status_code == 200 and response.json() == {"resend_available_in": 60}
    assert mail.outbox == []


def test_resend_registration_for_verified_account_sends_nothing(api_client):
    ShopFactory(owner=UserFactory(email="verifie@example.com"))
    response = api_client.post(RESEND, {"email": "verifie@example.com", "purpose": "REGISTRATION"})
    assert response.status_code == 200
    assert mail.outbox == []


def test_resend_password_reset_too_soon_is_silent(api_client, django_capture_on_commit_callbacks):
    UserFactory(email="client@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        first = api_client.post(
            RESEND, {"email": "client@example.com", "purpose": "PASSWORD_RESET"}
        )
        second = api_client.post(
            RESEND, {"email": "client@example.com", "purpose": "PASSWORD_RESET"}
        )
    assert first.status_code == second.status_code == 200
    assert len(mail.outbox) == 1


def test_resend_rejects_unknown_purpose(api_client):
    response = api_client.post(RESEND, {"email": EMAIL, "purpose": "EMAIL_CHANGE"})
    assert response.status_code == 400 and "purpose" in response.json()["error"]["details"]
