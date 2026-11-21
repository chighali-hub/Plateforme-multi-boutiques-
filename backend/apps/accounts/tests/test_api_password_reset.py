from datetime import timedelta

import pytest
from django.core import mail
from django.core.signing import TimestampSigner
from django.utils import timezone

from apps.accounts.models import OtpCode
from apps.accounts.services import PASSWORD_RESET_SALT
from apps.accounts.tests.factories import AdminUserFactory, UserFactory
from apps.accounts.tests.helpers import error_code, last_code_sent_to
from apps.accounts.tokens import issue_tokens
from apps.core.models import AuditLog
from apps.shops.tests.factories import ShopFactory

pytestmark = pytest.mark.django_db
FORGOT = "/api/v1/auth/password/forgot/"
VERIFY = "/api/v1/auth/password/verify-code/"
RESET = "/api/v1/auth/password/reset/"
REFRESH = "/api/v1/auth/token/refresh/"
NEW_PASSWORD = "NouveauSecret!2026"


@pytest.fixture
def user():
    return ShopFactory(owner=UserFactory(email="aicha@example.com"), pending=True).owner


@pytest.fixture
def ask_code(api_client, django_capture_on_commit_callbacks):
    def _ask(email="aicha@example.com"):
        with django_capture_on_commit_callbacks(execute=True):
            return api_client.post(FORGOT, {"email": email})

    return _ask


@pytest.fixture
def reset_token(api_client, user, ask_code):
    ask_code()
    response = api_client.post(VERIFY, {"email": user.email, "code": last_code_sent_to(user.email)})
    return response.json()["reset_token"]


def _reset(api_client, token, password=NEW_PASSWORD, confirm=None):
    return api_client.post(
        RESET,
        {
            "reset_token": token,
            "new_password": password,
            "new_password_confirm": confirm or password,
        },
    )


def test_forgot_same_response_for_known_and_unknown_email(user, ask_code):
    known = ask_code(user.email)
    unknown = ask_code("inconnu@example.com")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"otp_expires_in": 600, "resend_available_in": 60}
    assert [message.to for message in mail.outbox] == [[user.email]]


def test_forgot_works_for_admin(ask_code):
    admin = AdminUserFactory()
    ask_code(admin.email)
    assert OtpCode.objects.filter(user=admin, purpose="PASSWORD_RESET").exists()


def test_forgot_does_not_resend_during_cooldown(user, ask_code):
    ask_code()
    ask_code()
    assert len(mail.outbox) == 1


def test_full_reset_flow(api_client, user, reset_token):
    sessions = [issue_tokens(user) for _ in range(2)]

    response = _reset(api_client, reset_token)

    assert response.status_code == 204
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    for tokens in sessions:
        assert error_code(api_client.post(REFRESH, {"refresh": tokens["refresh"]})) == (
            "TOKEN_INVALID"
        )
    assert AuditLog.objects.filter(action="PASSWORD_RESET", actor=user).count() == 1
    login = api_client.post(
        "/api/v1/auth/shop/login/", {"email": user.email, "password": NEW_PASSWORD}
    )
    assert login.status_code == 200


def test_verify_code_returns_token_valid_15_minutes(api_client, user, ask_code):
    ask_code()
    response = api_client.post(VERIFY, {"email": user.email, "code": last_code_sent_to(user.email)})
    assert response.status_code == 200
    assert response.json()["expires_in"] == 900


def test_reset_token_is_single_use(api_client, reset_token):
    assert _reset(api_client, reset_token).status_code == 204
    response = _reset(api_client, reset_token, "EncoreAutre!2026")
    assert response.status_code == 400 and error_code(response) == "RESET_TOKEN_INVALID"


def test_reset_token_expires_after_15_minutes(api_client, user, reset_token, monkeypatch):
    real_time = __import__("time").time
    monkeypatch.setattr("django.core.signing.time.time", lambda: real_time() + 15 * 60 + 1)
    response = _reset(api_client, reset_token)
    assert error_code(response) == "RESET_TOKEN_INVALID"
    user.refresh_from_db()
    assert not user.check_password(NEW_PASSWORD)


def test_reset_token_invalidated_by_newer_code(api_client, user, reset_token, ask_code):
    OtpCode.objects.update(created_at=timezone.now() - timedelta(seconds=61))
    ask_code()
    assert error_code(_reset(api_client, reset_token)) == "RESET_TOKEN_INVALID"


@pytest.mark.parametrize("token", ["faux", "1:abc:def"])
def test_reset_with_forged_token(api_client, token):
    assert error_code(_reset(api_client, token)) == "RESET_TOKEN_INVALID"


def test_reset_with_token_signed_for_another_purpose(api_client, user):
    otp = OtpCode.objects.create(
        user=user,
        purpose="EMAIL_CHANGE",
        sent_to=user.email,
        code_hash="x",
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    token = TimestampSigner(salt=PASSWORD_RESET_SALT).sign_object({"user": user.pk, "otp": otp.pk})
    assert error_code(_reset(api_client, token)) == "RESET_TOKEN_INVALID"


def test_reset_token_from_other_salt_rejected(api_client, user):
    token = TimestampSigner(salt="autre").sign_object({"user": user.pk, "otp": 1})
    assert error_code(_reset(api_client, token)) == "RESET_TOKEN_INVALID"


def test_reset_enforces_password_policy(api_client, reset_token):
    response = _reset(api_client, reset_token, "12345678")
    assert response.status_code == 400
    assert "new_password" in response.json()["error"]["details"]


def test_reset_password_confirmation_must_match(api_client, reset_token):
    response = _reset(api_client, reset_token, NEW_PASSWORD, "Different!2026")
    assert "new_password_confirm" in response.json()["error"]["details"]


def test_verify_code_wrong_and_unknown_email(api_client, user, ask_code):
    ask_code()
    code = last_code_sent_to(user.email)
    wrong = "000000" if code != "000000" else "111111"
    assert error_code(api_client.post(VERIFY, {"email": user.email, "code": wrong})) == (
        "OTP_INVALID"
    )
    assert error_code(api_client.post(VERIFY, {"email": "x@example.com", "code": code})) == (
        "OTP_EXPIRED"
    )
