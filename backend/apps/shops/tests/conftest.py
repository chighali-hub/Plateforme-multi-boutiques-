import pytest

from apps.core.models import PlatformSettings


@pytest.fixture
def admin_whatsapp(db):
    """Numero WhatsApp et e-mail de contact de l'administrateur renseignes."""
    row = PlatformSettings.load()
    row.admin_whatsapp = "22334455"
    row.admin_contact_email = "contact@plateforme.mr"
    row.save()
    return row.admin_whatsapp
