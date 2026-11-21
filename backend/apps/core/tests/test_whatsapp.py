from apps.core.whatsapp import build_whatsapp_url


def test_build_whatsapp_url_adds_country_prefix():
    assert build_whatsapp_url("22334455") == "https://wa.me/22222334455"


def test_build_whatsapp_url_encodes_text():
    url = build_whatsapp_url("36123456", "Bonjour, commande CMD-2026-000042 & merci?")
    assert url == (
        "https://wa.me/22236123456?text=Bonjour%2C%20commande%20CMD-2026-000042%20%26%20merci%3F"
    )


def test_build_whatsapp_url_encodes_arabic_text():
    url = build_whatsapp_url("36123456", "مرحبا")
    assert url == "https://wa.me/22236123456?text=%D9%85%D8%B1%D8%AD%D8%A8%D8%A7"


def test_build_whatsapp_url_without_text_has_no_query():
    assert "?" not in build_whatsapp_url("36123456", "")
