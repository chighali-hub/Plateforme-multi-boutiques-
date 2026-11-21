import pytest

from apps.core.text import normalize_search_text


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("MELHFA", "melhfa"),  # 1. minuscules
        ("Téléphone à l'écran", "telefone a l ecran"),  # 2. accents latins (+ ph, ponctuation)
        ("Aïcha", "aicha"),
        ("مَلْحَفَة", "ملحفه"),  # 3. tashkeel + ta marbuta
        ("ملـــحفة", "ملحفه"),  # 3. tatweel
        ("أحذية", "احذيه"),  # 3. alif hamza
        ("إيمان", "ايمان"),
        ("آمال", "امال"),
        ("على", "علي"),  # 3. alif maqsura
        ("مؤمن", "مومن"),  # 3. waw hamza
        ("شاطئ", "شاطي"),  # 3. ya hamza
        ("mel7fa", "melhfa"),  # 4. arabizi 7 -> h
        ("sa3a", "sa"),  # 4. 3 -> a, puis lettres doublees reduites (saaa -> sa)
        ("da9iq", "daqiq"),  # 4. 9 -> q
        ("ba5our", "bakhour"),  # 4. 5 -> kh
        ("so2al", "soal"),  # 4. 2 -> a puis reduction
        ("Telephones", "telefones"),  # 5. ph -> f
        ("Accessoires", "acesoires"),  # 6. lettres doublees
        ("voile,  noir ! (neuf)", "voile noir neuf"),  # 7. ponctuation et espaces
        ("snake_case", "snake case"),
    ],
)
def test_normalize_search_text_applies_each_rule(raw, expected):
    assert normalize_search_text(raw) == expected


@pytest.mark.parametrize("raw", ["Melhfa", "MELHFA", "mel7fa"])
def test_normalize_search_text_spellings_converge(raw):
    assert normalize_search_text(raw) == "melhfa"


def test_normalize_search_text_keeps_digits_outside_words():
    assert normalize_search_text("Lot de 100 voiles 7") == "lot de 100 voiles 7"


def test_normalize_search_text_keeps_repeated_digits():
    assert normalize_search_text("2000 MRU") == "2000 mru"


@pytest.mark.parametrize("raw", [None, "", "   ", "!!!"])
def test_normalize_search_text_empty_input_returns_empty_string(raw):
    assert normalize_search_text(raw) == ""
