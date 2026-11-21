from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import OtpCode
from apps.accounts.tests.factories import DEFAULT_PASSWORD, UserFactory
from apps.accounts.tests.helpers import error_code, last_code_sent_to
from apps.accounts.tokens import issue_tokens
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db
CHANGE_PASSWORD = "/api/v1/account/change-password/"
EMAIL_REQUEST = "/api/v1/account/change-email/request/"
EMAIL_CONFIRM = "/api/v1/account/change-email/confirm/"
REFRESH = "/api/v1/auth/token/refresh/"
NEW_EMAIL = "contact@aichamode.mr"


def _change_password(client, current=DEFAULT_PASSWORD, new="NouveauSecret!2026", confirm=None):
    return client.post(
        CHANGE_PASSWORD,
        {"current_password": current, "new_password": new, "new_password_confirm": confirm or new},
    )


def test_change_password_returns_new_tokens_and_closes_other_sessions(api_client, shop_client):
    user = shop_client.user
    other_session = issue_tokens(user)

    response = _change_password(shop_client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access", "refresh", "user"}
    user.refresh_from_db()
    assert user.check_password("NouveauSecret!2026")
    assert api_client.post(REFRESH, {"refresh": other_session["refresh"]}).status_code == 401
    assert api_client.post(REFRESH, {"refresh": body["refresh"]}).status_code == 200


def test_change_password_wrong_current(shop_client):
    response = _change_password(shop_client, current="Mauvais!2026x")
    assert response.status_code == 400
    assert "current_password" in response.json()["error"]["details"]
    shop_client.user.refresh_from_db()
    assert shop_client.user.check_password(DEFAULT_PASSWORD)


@pytest.mark.parametrize(
    "new, confirm, field",
    [
        ("12345678", None, "new_password"),
        ("NouveauSecret!2026", "Autre!2026x", "new_password_confirm"),
    ],
)
def test_change_password_validation(shop_client, new, confirm, field):
    response = _change_password(shop_client, new=new, confirm=confirm)
    assert response.status_code == 400 and field in response.json()["error"]["details"]


def test_change_password_works_for_admin(admin_client):
    assert _change_password(admin_client).status_code == 200


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
def test_account_endpoints_state_matrix(make_shop_client, state, expected):
    assert _change_password(make_shop_client(state)).status_code == expected


def test_account_endpoints_require_authentication(api_client):
    for url in (CHANGE_PASSWORD, EMAIL_REQUEST, EMAIL_CONFIRM):
        response = api_client.post(url, {})
        assert response.status_code == 401
        assert error_code(response) == "AUTHENTICATION_REQUIRED"


@pytest.fixture
def request_change(django_capture_on_commit_callbacks):
    def _request(client, new_email=NEW_EMAIL, password=DEFAULT_PASSWORD):
        with django_capture_on_commit_callbacks(execute=True):
            return client.post(
                EMAIL_REQUEST, {"new_email": new_email, "current_password": password}
            )

    return _request


def test_email_change_full_flow(shop_client, request_change, django_capture_on_commit_callbacks):
    old_email = shop_client.user.email

    response = request_change(shop_client, "Contact@AichaMode.mr")

    assert response.status_code == 200
    assert response.json() == {
        "sent_to": NEW_EMAIL,
        "otp_expires_in": 600,
        "resend_available_in": 60,
    }
    assert mail.outbox[-1].to == [NEW_EMAIL]
    with django_capture_on_commit_callbacks(execute=True):
        confirm = shop_client.post(EMAIL_CONFIRM, {"code": last_code_sent_to(NEW_EMAIL)})
    assert confirm.status_code == 200
    assert confirm.json()["email"] == NEW_EMAIL
    shop_client.user.refresh_from_db()
    assert shop_client.user.email == NEW_EMAIL
    assert mail.outbox[-1].to == [old_email]
    assert NEW_EMAIL in mail.outbox[-1].body
    entry = AuditLog.objects.get(action="EMAIL_CHANGED")
    assert entry.metadata == {"old_email": old_email, "new_email": NEW_EMAIL}


def test_email_change_requires_current_password(shop_client, request_change):
    response = request_change(shop_client, password="Mauvais!2026x")
    assert response.status_code == 400
    assert "current_password" in response.json()["error"]["details"]
    assert mail.outbox == []


def test_email_change_same_address_refused(shop_client, request_change):
    response = request_change(shop_client, shop_client.user.email.upper())
    assert response.status_code == 400 and "new_email" in response.json()["error"]["details"]


def test_email_change_to_taken_address(shop_client, request_change):
    UserFactory(email=NEW_EMAIL)
    response = request_change(shop_client)
    assert response.status_code == 409 and error_code(response) == "EMAIL_ALREADY_USED"


def test_email_change_resend_too_soon(shop_client, request_change):
    request_change(shop_client)
    response = request_change(shop_client)
    assert response.status_code == 429 and error_code(response) == "OTP_RESEND_TOO_SOON"
    OtpCode.objects.update(created_at=timezone.now() - timedelta(seconds=61))
    assert request_change(shop_client).status_code == 200


def test_email_change_address_taken_in_between(shop_client, request_change):
    request_change(shop_client)
    UserFactory(email=NEW_EMAIL)
    response = shop_client.post(EMAIL_CONFIRM, {"code": last_code_sent_to(NEW_EMAIL)})
    assert response.status_code == 409 and error_code(response) == "EMAIL_ALREADY_USED"
    shop_client.user.refresh_from_db()
    assert shop_client.user.email != NEW_EMAIL


def test_email_change_wrong_code(shop_client, request_change):
    request_change(shop_client)
    code = last_code_sent_to(NEW_EMAIL)
    wrong = "000000" if code != "000000" else "111111"
    response = shop_client.post(EMAIL_CONFIRM, {"code": wrong})
    assert response.status_code == 400 and error_code(response) == "OTP_INVALID"


def test_email_change_confirm_without_request(shop_client):
    response = shop_client.post(EMAIL_CONFIRM, {"code": "123456"})
    assert error_code(response) == "OTP_EXPIRED"


def test_email_change_code_of_another_user_is_useless(
    shop_client, other_shop_client, request_change
):
    request_change(other_shop_client)
    response = shop_client.post(EMAIL_CONFIRM, {"code": last_code_sent_to(NEW_EMAIL)})
    assert error_code(response) == "OTP_EXPIRED"
    other_shop_client.user.refresh_from_db()
    assert other_shop_client.user.email != NEW_EMAIL
