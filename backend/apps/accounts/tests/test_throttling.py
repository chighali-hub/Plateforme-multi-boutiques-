"""Les limitations de debit sont coupees dans les parametres de test ; ces tests
les reactivent vue par vue pour verifier les portees et les valeurs."""

import pytest
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts import views
from apps.accounts.tests.helpers import error_code

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "view, scope",
    [
        (views.ShopRegisterView, "auth"),
        (views.ShopLoginView, "auth"),
        (views.AdminLoginView, "admin_auth"),
        (views.VerifyEmailView, "otp"),
        (views.ResendOtpView, "otp"),
        (views.ForgotPasswordView, "otp"),
        (views.VerifyResetCodeView, "otp"),
        (views.ResetPasswordView, "otp"),
        (views.ChangeEmailRequestView, "otp"),
        (views.ChangeEmailConfirmView, "otp"),
    ],
)
def test_sensitive_views_declare_their_scope(view, scope):
    assert view.throttle_scope == scope


def test_scoped_throttle_enabled_by_default_settings():
    from django.conf import settings

    from config.settings import base

    assert (
        "rest_framework.throttling.ScopedRateThrottle"
        in (base.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"])
    )
    assert base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["admin_auth"] == "5/min"
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] == ()


def test_admin_login_blocked_after_five_attempts(api_client, monkeypatch):
    monkeypatch.setattr(views.AdminLoginView, "throttle_classes", [ScopedRateThrottle])
    payload = {"email": "admin@example.com", "password": "Mauvais!2026x"}
    statuses = [api_client.post("/api/v1/auth/admin/login/", payload).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]
    response = api_client.post("/api/v1/auth/admin/login/", payload)
    assert error_code(response) == "THROTTLED"
    assert response.json()["error"]["details"]["retry_after"] > 0


def test_otp_verification_blocked_after_five_requests(api_client, monkeypatch):
    monkeypatch.setattr(views.VerifyEmailView, "throttle_classes", [ScopedRateThrottle])
    payload = {"email": "x@example.com", "code": "123456"}
    statuses = [
        api_client.post("/api/v1/auth/shop/verify-email/", payload).status_code for _ in range(6)
    ]
    assert statuses[-1] == 429 and statuses[:5] == [400] * 5
