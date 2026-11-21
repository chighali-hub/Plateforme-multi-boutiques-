"""Choix de la langue des champs traduits. Voir 05-aspects-transversaux.md section 7.3."""

from typing import Any

SUPPORTED_LANGUAGES = ("fr", "ar")
DEFAULT_LANGUAGE = "fr"


def normalize_language(lang: str | None) -> str:
    """Ramene une valeur libre (en-tete, parametre) a 'fr' ou 'ar'."""
    if lang:
        short = str(lang).split("-")[0].lower()
        if short in SUPPORTED_LANGUAGES:
            return short
    return DEFAULT_LANGUAGE


def pick(obj: Any, field: str, lang: str | None) -> str:
    """Renvoie `<field>_<lang>`, sinon le champ de l'autre langue."""
    primary = normalize_language(lang)
    other = "ar" if primary == "fr" else "fr"
    value = getattr(obj, f"{field}_{primary}", "") or ""
    return value or (getattr(obj, f"{field}_{other}", "") or "")
