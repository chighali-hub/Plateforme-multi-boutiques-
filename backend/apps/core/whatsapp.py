"""Construction des liens WhatsApp. Voir 05-aspects-transversaux.md section 11."""

from urllib.parse import quote

WHATSAPP_BASE_URL = "https://wa.me/"
MAURITANIA_COUNTRY_CODE = "222"


def build_whatsapp_url(phone: str, text: str | None = None) -> str:
    """Renvoie https://wa.me/222<phone>, suivi du texte encode s'il est fourni.

    `phone` est un numero deja normalise sur 8 chiffres.
    """
    url = f"{WHATSAPP_BASE_URL}{MAURITANIA_COUNTRY_CODE}{phone}"
    if text:
        url = f"{url}?text={quote(str(text), safe='')}"
    return url
