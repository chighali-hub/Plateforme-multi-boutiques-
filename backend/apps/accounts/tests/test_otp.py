from datetime import timedelta

import pytest
from django.contrib.auth.hashers import check_password
from django.utils import timezone

from apps.accounts import otp as otp_service
from apps.accounts.models import OtpCode
from apps.accounts.tests.factories import UserFactory
from apps.core.exceptions import OtpExpired, OtpInvalid, OtpTooManyAttempts

pytestmark = pytest.mark.django_db
PURPOSE = OtpCode.Purpose.REGISTRATION


@pytest.fixture
def user():
    return UserFactory(is_email_verified=False)


def test_generate_code_is_six_digits_with_leading_zeros(monkeypatch):
    monkeypatch.setattr(otp_service.secrets, "randbelow", lambda bound: 42)
    assert otp_service.generate_code() == "000042"


def test_issue_otp_stores_only_a_hash(user):
    issued = otp_service.issue_otp(user, PURPOSE, user.email)
    issued.otp.refresh_from_db()
    assert issued.code not in issued.otp.code_hash
    assert check_password(issued.code, issued.otp.code_hash)


def test_issue_otp_expires_after_ten_minutes(user, freeze_now):
    now = freeze_now(timezone.now())
    issued = otp_service.issue_otp(user, PURPOSE, user.email)
    assert issued.otp.expires_at == now + timedelta(minutes=10)


def test_new_code_invalidates_previous_ones(user):
    first = otp_service.issue_otp(user, PURPOSE, user.email)
    second = otp_service.issue_otp(user, PURPOSE, user.email)
    first.otp.refresh_from_db()
    assert first.otp.consumed_at is not None
    with pytest.raises(OtpInvalid):
        otp_service.verify_otp(user, PURPOSE, first.code if first.code != second.code else "x")
    assert otp_service.verify_otp(user, PURPOSE, second.code).pk == second.otp.pk


def test_other_purposes_are_not_invalidated(user):
    reset = otp_service.issue_otp(user, OtpCode.Purpose.PASSWORD_RESET, user.email)
    otp_service.issue_otp(user, PURPOSE, user.email)
    reset.otp.refresh_from_db()
    assert reset.otp.consumed_at is None


def test_verify_consumes_the_code(user):
    issued = otp_service.issue_otp(user, PURPOSE, user.email)
    otp_service.verify_otp(user, PURPOSE, issued.code)
    with pytest.raises(OtpExpired):
        otp_service.verify_otp(user, PURPOSE, issued.code)


def test_verify_without_consume_keeps_code(user):
    issued = otp_service.issue_otp(user, PURPOSE, user.email)
    otp_service.verify_otp(user, PURPOSE, issued.code, consume=False)
    issued.otp.refresh_from_db()
    assert issued.otp.consumed_at is None


def test_code_expired_after_ten_minutes(user, freeze_now):
    start = timezone.now()
    freeze_now(start)
    issued = otp_service.issue_otp(user, PURPOSE, user.email)
    freeze_now(start + timedelta(minutes=10, seconds=1))
    with pytest.raises(OtpExpired):
        otp_service.verify_otp(user, PURPOSE, issued.code)


def test_code_still_valid_just_before_expiry(user, freeze_now):
    start = timezone.now()
    freeze_now(start)
    issued = otp_service.issue_otp(user, PURPOSE, user.email)
    freeze_now(start + timedelta(minutes=9, seconds=59))
    assert otp_service.verify_otp(user, PURPOSE, issued.code)


def test_no_code_gives_expired(user):
    with pytest.raises(OtpExpired):
        otp_service.verify_otp(user, PURPOSE, "123456")


def test_wrong_code_counts_attempts_then_blocks(user):
    issued = otp_service.issue_otp(user, PURPOSE, user.email)
    wrong = "000000" if issued.code != "000000" else "111111"
    for attempts_left in (4, 3, 2, 1):
        with pytest.raises(OtpInvalid) as error:
            otp_service.verify_otp(user, PURPOSE, wrong)
        assert error.value.details == {"attempts_left": attempts_left}
    with pytest.raises(OtpTooManyAttempts):
        otp_service.verify_otp(user, PURPOSE, wrong)
    # Meme le bon code est refuse apres 5 essais.
    with pytest.raises(OtpTooManyAttempts):
        otp_service.verify_otp(user, PURPOSE, issued.code)


def test_seconds_until_resend(user, freeze_now):
    start = timezone.now()
    freeze_now(start)
    assert otp_service.seconds_until_resend(user, PURPOSE) == 0
    otp_service.issue_otp(user, PURPOSE, user.email)
    freeze_now(start + timedelta(seconds=23))
    assert otp_service.seconds_until_resend(user, PURPOSE) == 37
    freeze_now(start + timedelta(seconds=60))
    assert otp_service.seconds_until_resend(user, PURPOSE) == 0
