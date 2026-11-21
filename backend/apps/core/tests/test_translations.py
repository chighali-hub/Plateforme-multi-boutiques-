"""Porte de parite des traductions : chaque texte francais a sa traduction arabe,
et le catalogue compile (.mo) correspond au catalogue source (.po)."""

import ast
import gettext
from pathlib import Path

from django.conf import settings

LOCALE_DIR = Path(settings.LOCALE_PATHS[0]) / "ar" / "LC_MESSAGES"


def parse_po(path: Path) -> list[dict]:
    """Analyse minimale d'un fichier .po : msgid, msgid_plural, msgstr, msgstr[n]."""
    entries: list[dict] = []
    current: dict = {}
    key = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            if current:
                entries.append(current)
                current, key = {}, None
            continue
        if line.startswith('"'):
            current[key] += ast.literal_eval(line)
            continue
        key, _sep, value = line.partition(" ")
        current[key] = ast.literal_eval(value)
    if current:
        entries.append(current)
    return [entry for entry in entries if entry.get("msgid")]


def test_every_arabic_entry_is_translated():
    entries = parse_po(LOCALE_DIR / "django.po")
    assert entries, "Catalogue arabe vide"
    untranslated = [
        entry["msgid"]
        for entry in entries
        if not all(value for key, value in entry.items() if key.startswith("msgstr"))
    ]
    assert untranslated == []


def test_compiled_catalogue_matches_source():
    with (LOCALE_DIR / "django.mo").open("rb") as handle:
        compiled = gettext.GNUTranslations(handle)
    for entry in parse_po(LOCALE_DIR / "django.po"):
        if "msgid_plural" in entry:
            assert compiled.ngettext(entry["msgid"], entry["msgid_plural"], 3) == entry["msgstr[3]"]
        else:
            assert compiled.gettext(entry["msgid"]) == entry["msgstr"], entry["msgid"]
