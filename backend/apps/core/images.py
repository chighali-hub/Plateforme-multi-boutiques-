"""Traitement des images envoyees. Voir 05-aspects-transversaux.md section 8.4.

Toute image enregistree passe par ce module : orientation corrigee, metadonnees
(EXIF, GPS) supprimees. Les images publiques sont converties en WebP.
"""

import io
import uuid
from dataclasses import dataclass

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from .validators import validate_image_file

WEBP_QUALITY = 82
LOGO_MAX_DIMENSION = 512
PRODUCT_MAX_DIMENSION = 1600
THUMBNAIL_MAX_DIMENSION = 400

_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


@dataclass(frozen=True)
class ProcessedImage:
    image: ContentFile
    thumbnail: ContentFile | None = None


def _random_name(extension: str) -> str:
    return f"{uuid.uuid4().hex}.{extension}"


def _load_upright(file) -> Image.Image:
    file.seek(0)
    with Image.open(file) as source:
        source.load()
        upright = ImageOps.exif_transpose(source)
    return upright


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _encode_webp(image: Image.Image, max_dimension: int) -> ContentFile:
    resized = image.copy()
    resized.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    # Une nouvelle image sans `exif` ni `icc_profile` : aucune metadonnee n'est copiee.
    resized.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=4)
    return ContentFile(buffer.getvalue(), name=_random_name("webp"))


def process_image(
    file,
    *,
    max_dimension: int,
    thumbnail_dimension: int | None = None,
) -> ProcessedImage:
    """Valide puis convertit une image publique en WebP.

    L'image est reduite a `max_dimension` pixels sur son plus grand cote (jamais
    agrandie). Si `thumbnail_dimension` est fourni, une miniature est produite.
    Leve FileTooLarge ou ValidationError (voir validate_image_file).
    """
    validate_image_file(file)
    image = _to_rgb(_load_upright(file))
    main = _encode_webp(image, max_dimension)
    thumbnail = _encode_webp(image, thumbnail_dimension) if thumbnail_dimension else None
    return ProcessedImage(image=main, thumbnail=thumbnail)


def process_logo(file) -> ContentFile:
    return process_image(file, max_dimension=LOGO_MAX_DIMENSION).image


def process_product_image(file) -> ProcessedImage:
    return process_image(
        file, max_dimension=PRODUCT_MAX_DIMENSION, thumbnail_dimension=THUMBNAIL_MAX_DIMENSION
    )


def sanitize_private_image(file) -> ContentFile:
    """Image privee (carte d'identite, capture de paiement).

    Pas de reduction de qualite : elle doit rester lisible. Les metadonnees sont
    supprimees et le format d'origine est conserve.
    """
    info = validate_image_file(file)
    image = _load_upright(file)
    if info.format == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    clean = Image.new(image.mode, image.size)
    clean.paste(image)
    if image.mode == "P" and image.getpalette():
        clean.putpalette(image.getpalette())
    buffer = io.BytesIO()
    save_options = {"JPEG": {"quality": 95}, "WEBP": {"lossless": True}, "PNG": {}}
    clean.save(buffer, format=info.format, **save_options[info.format])
    return ContentFile(buffer.getvalue(), name=_random_name(_EXTENSIONS[info.format]))
