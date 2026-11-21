from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
TARGET = "apps.accounts.management.commands.create_admin.getpass"


def _answers(monkeypatch, *values):
    replies = iter(values)
    monkeypatch.setattr(TARGET, lambda prompt="": next(replies))


def test_create_admin(monkeypatch):
    _answers(monkeypatch, "Admin!Secret2026", "Admin!Secret2026")
    out = StringIO()
    call_command("create_admin", "--email", "Admin@Plateforme.MR", stdout=out)
    admin = User.objects.get(email="admin@plateforme.mr")
    assert admin.role == User.Role.ADMIN and admin.is_email_verified
    assert admin.check_password("Admin!Secret2026")
    assert "Admin!Secret2026" not in out.getvalue()


def test_create_admin_retries_after_mismatch_and_weak_password(monkeypatch):
    _answers(
        monkeypatch,
        "Admin!Secret2026",
        "autre",
        "12345678",
        "12345678",
        "Admin!Secret2026",
        "Admin!Secret2026",
    )
    call_command(
        "create_admin", "--email", "admin@plateforme.mr", stdout=StringIO(), stderr=StringIO()
    )
    assert User.objects.filter(email="admin@plateforme.mr").exists()


def test_create_admin_gives_up_after_three_bad_attempts(monkeypatch):
    _answers(monkeypatch, *["a", "b"] * 3)
    with pytest.raises(CommandError):
        call_command("create_admin", "--email", "admin@plateforme.mr", stderr=StringIO())
    assert not User.objects.exists()


def test_create_admin_refuses_existing_email():
    UserFactory(email="admin@plateforme.mr")
    with pytest.raises(CommandError):
        call_command("create_admin", "--email", "ADMIN@plateforme.mr")


def test_create_admin_refuses_invalid_email():
    with pytest.raises(CommandError):
        call_command("create_admin", "--email", "pas-un-email")
