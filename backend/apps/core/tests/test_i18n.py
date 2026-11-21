from types import SimpleNamespace

import pytest

from apps.core.i18n import normalize_language, pick


@pytest.mark.parametrize(
    "value, expected",
    [("ar", "ar"), ("AR", "ar"), ("ar-MR", "ar"), ("fr-FR", "fr"), ("en", "fr"), (None, "fr")],
)
def test_normalize_language(value, expected):
    assert normalize_language(value) == expected


def test_pick_returns_requested_language():
    obj = SimpleNamespace(name_fr="Voile", name_ar="خمار")
    assert pick(obj, "name", "ar") == "خمار"
    assert pick(obj, "name", "fr") == "Voile"


def test_pick_falls_back_to_other_language():
    assert pick(SimpleNamespace(name_fr="", name_ar="خمار"), "name", "fr") == "خمار"
    assert pick(SimpleNamespace(name_fr="Voile", name_ar=""), "name", "ar") == "Voile"
