import pytest

from apps.core.models import PlatformSettings


@pytest.fixture
def platform_settings(db):
    """Parametres renseignes : WhatsApp et e-mail de contact de l'administrateur."""
    row = PlatformSettings.load()
    row.admin_whatsapp = "22334455"
    row.admin_contact_email = "contact@plateforme.mr"
    row.save()
    return row


@pytest.fixture
def run_on_commit(django_capture_on_commit_callbacks):
    """Execute les callbacks on_commit (e-mails) declenches pendant l'appel."""

    def _run(func, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return func(*args, **kwargs)

    return _run
