"""Normalisation du texte pour la recherche.

La meme fonction est appliquee au texte stocke (search_name, search_text_*) et
au texte saisi par le client : les deux cotes sont compares sous la meme forme.
Regles : docs/Documentation-API/04-schema-base-de-donnees.md section 9.3.
"""

import re
import unicodedata

# Signes diacritiques arabes (tashkeel), alif suscrit, tatweel.
_ARABIC_DIACRITICS = re.compile("[ً-ْٰـ]")

# Formes arabes ramenees a une forme de base. Les lettres a hamza (U+0623,
# U+0625, U+0622, U+0624, U+0626) sont deja decomposees par NFKD ; la table
# les reprend pour ne pas dependre de cette decomposition.
_ARABIC_FOLDING = str.maketrans(
    {
        "أ": "ا",  # alif hamza dessus  -> alif
        "إ": "ا",  # alif hamza dessous -> alif
        "آ": "ا",  # alif madda         -> alif
        "ة": "ه",  # ta marbuta         -> ha
        "ى": "ي",  # alif maqsura       -> ya
        "ؤ": "و",  # waw hamza          -> waw
        "ئ": "ي",  # ya hamza           -> ya
    }
)

# Chiffres "arabizi" places entre deux lettres.
_ARABIZI = {"7": "h", "3": "a", "9": "q", "5": "kh", "2": "a"}
_ARABIZI_PATTERN = re.compile(r"(?<=[^\W\d_])([73952])(?=[^\W\d_])")

_DOUBLED_LETTERS = re.compile(r"([^\W\d_])\1+")
_NON_WORD = re.compile(r"[\W_]+")


def _strip_combining_marks(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_search_text(value: str | None) -> str:
    """Ramene un texte a sa forme de recherche.

    1. minuscules ; 2. accents latins retires ; 3. normalisation arabe ;
    4. chiffres arabizi entre deux lettres ; 5. ph -> f ; 6. lettres doublees
    reduites ; 7. ponctuation remplacee par une espace, espaces reduites.
    """
    if not value:
        return ""
    text = str(value).lower()
    text = text.translate(_ARABIC_FOLDING)
    text = _strip_combining_marks(text)
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.translate(_ARABIC_FOLDING)
    text = _ARABIZI_PATTERN.sub(lambda match: _ARABIZI[match.group(1)], text)
    text = text.replace("ph", "f")
    text = _DOUBLED_LETTERS.sub(r"\1", text)
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())
