import pytest

from apps.core.models import PlatformSettings


@pytest.fixture
def registration_data(image_file):
    """Fabrique : formulaire d'inscription complet et valide (RG-01)."""

    def _make(**overrides):
        data = {
            "shop_name": "Aïcha Mode",
            "logo": image_file("PNG", (900, 600), name="logo.png"),
            "description_fr": "Melhfas, voiles et parfums de qualité.",
            "description_ar": "ملاحف و خمارات و عطور عالية الجودة",
            "address": "Tevragh Zeina, Nouakchott",
            "phone": "+222 36 12 34 56",
            "whatsapp": "46123456",
            "email": "Aicha@Example.com",
            "password": "MotDePasse!2026",
            "password_confirm": "MotDePasse!2026",
            "owner_full_name": "Aicha Mint Ahmed",
            "id_card_front": image_file("JPEG", (1200, 800), name="recto.jpg"),
            "id_card_back": image_file("JPEG", (1200, 800), name="verso.jpg"),
        }
        data.update(overrides)
        return {key: value for key, value in data.items() if value is not None}

    return _make


@pytest.fixture
def admin_whatsapp(db):
    row = PlatformSettings.load()
    row.admin_whatsapp = "22334455"
    row.save()
    return row.admin_whatsapp
