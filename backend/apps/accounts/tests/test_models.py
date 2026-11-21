import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import OtpCode, User
from apps.accounts.tests.factories import OtpCodeFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_email_stored_lowercase_by_database_constraint():
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email="Mixed@Example.com")])


def test_email_unique_ignoring_case():
    UserFactory(email="aicha@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        UserFactory(email="AICHA@example.com")


def test_unknown_role_refused():
    user = UserFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(role="ROOT")


def test_password_is_never_stored_in_clear():
    user = UserFactory(password="Secret!2026x")
    user.refresh_from_db()
    assert "Secret!2026x" not in user.password
    assert user.check_password("Secret!2026x")


def test_otp_purpose_constrained():
    with pytest.raises(IntegrityError), transaction.atomic():
        OtpCodeFactory(purpose="LOGIN")


def test_otp_codes_deleted_with_user():
    code = OtpCodeFactory()
    code.user.delete()
    assert not OtpCode.objects.exists()
