"""Validateurs communs : telephone, couleur, images.

Voir 05-aspects-transversaux.md sections 8.3 et 11, et 07-securite.md section 4.
"""

import re
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError

from .exceptions import FileTooLarge

PHONE_PATTERN = r"^[234][0-9]{7}$"
HEX_COLOR_PATTERN = r"^#[0-9A-F]{6}$"

PHONE_ERROR = _("Saisissez un numéro mauritanien de 8 chiffres commençant par 2, 3 ou 4.")
COLOR_ERROR = _("Saisissez une couleur au format #RRGGBB.")
IMAGE_FORMAT_ERROR = _("Le fichier doit être une image JPEG, PNG ou WebP valide.")
IMAGE_DIMENSIONS_ERROR = _("L'image dépasse les dimensions autorisées.")

# Validateurs de modele : ils controlent la forme stockee (deja normalisee).
phone_validator = RegexValidator(PHONE_PATTERN, PHONE_ERROR, code="invalid_phone")
hex_color_validator = RegexValidator(HEX_COLOR_PATTERN, COLOR_ERROR, code="invalid_color")

_PHONE_SEPARATORS = re.compile(r"[\s.\-()]")
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


def normalize_phone(value: str | None) -> str:
    """Renvoie le numero sur 8 chiffres ou leve ValidationError.

    Accepte les espaces, points, tirets, et les prefixes +222 ou 00222.
    """
    raw = _PHONE_SEPARATORS.sub("", str(value or ""))
    for prefix in ("+222", "00222"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    if not re.fullmatch(PHONE_PATTERN, raw):
        raise ValidationError(PHONE_ERROR, code="invalid_phone")
    return raw


def normalize_hex_color(value: str | None) -> str:
    """Renvoie la couleur en majuscules (#RRGGBB) ou leve ValidationError."""
    color = str(value or "").strip().upper()
    if not re.fullmatch(HEX_COLOR_PATTERN, color):
        raise ValidationError(COLOR_ERROR, code="invalid_color")
    return color


@dataclass(frozen=True)
class ImageInfo:
    format: str
    width: int
    height: int


def validate_image_file(file, *, field_name: str | None = None) -> ImageInfo:
    """Verifie qu'un fichier envoye est une vraie image acceptee.

    1. taille <= UPLOAD_IMAGE_MAX_BYTES, sinon FileTooLarge (413) ;
    2. contenu reconnu par Pillow comme JPEG, PNG ou WebP (l'extension ne compte pas) ;
    3. dimensions <= UPLOAD_IMAGE_MAX_DIMENSION.
    Le curseur du fichier est remis au debut.
    """
    max_bytes = settings.UPLOAD_IMAGE_MAX_BYTES
    max_dimension = settings.UPLOAD_IMAGE_MAX_DIMENSION
    size = getattr(file, "size", None)
    if size is not None and size > max_bytes:
        details = {"max_bytes": max_bytes}
        if field_name:
            details = {"field": field_name, **details}
        raise FileTooLarge(details=details)

    try:
        file.seek(0)
        with Image.open(file) as probe:
            image_format = probe.format
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ValidationError(IMAGE_FORMAT_ERROR, code="invalid_image") from None
    finally:
        file.seek(0)

    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError(IMAGE_FORMAT_ERROR, code="invalid_image")
    if width > max_dimension or height > max_dimension:
        raise ValidationError(IMAGE_DIMENSIONS_ERROR, code="image_too_large")
    return ImageInfo(format=image_format, width=width, height=height)
