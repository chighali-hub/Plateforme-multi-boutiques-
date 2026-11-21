import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.images import (
    process_image,
    process_logo,
    process_product_image,
    sanitize_private_image,
)

GPS_IFD = 0x8825
ORIENTATION = 0x0112
MAKE = 0x010F


def _jpeg_with_exif(size=(300, 200), orientation=None) -> SimpleUploadedFile:
    image = Image.new("RGB", size, (10, 120, 60))
    exif = Image.Exif()
    exif[MAKE] = "AppareilTest"
    exif[GPS_IFD] = {1: "N", 2: (18.0, 5.0, 0.0)}
    if orientation:
        exif[ORIENTATION] = orientation
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return SimpleUploadedFile("photo.jpg", buffer.getvalue(), content_type="image/jpeg")


def _open(content_file) -> Image.Image:
    content_file.seek(0)
    image = Image.open(io.BytesIO(content_file.read()))
    image.load()
    return image


def test_process_image_outputs_webp_with_random_name(image_file):
    result = process_image(image_file(), max_dimension=1600)
    assert _open(result.image).format == "WEBP"
    assert result.image.name.endswith(".webp")
    assert "photo" not in result.image.name
    assert result.thumbnail is None


def test_process_image_limits_largest_side(image_file):
    result = process_image(image_file(size=(1000, 500)), max_dimension=400)
    assert _open(result.image).size == (400, 200)


def test_process_image_never_upscales(image_file):
    result = process_image(image_file(size=(120, 80)), max_dimension=1600)
    assert _open(result.image).size == (120, 80)


def test_process_product_image_builds_image_and_thumbnail(image_file):
    result = process_product_image(image_file(size=(3200, 1600)))
    assert _open(result.image).size == (1600, 800)
    assert _open(result.thumbnail).size == (400, 200)
    assert result.image.name != result.thumbnail.name


def test_process_logo_limits_to_512(image_file):
    assert max(_open(process_logo(image_file(size=(2000, 1000)))).size) == 512


def test_process_image_removes_exif_and_gps():
    result = process_image(_jpeg_with_exif(), max_dimension=1600)
    output = _open(result.image)
    assert not output.getexif()
    assert "exif" not in output.info


def test_process_image_applies_exif_orientation_before_removing_it():
    # Orientation 6 : l'image doit etre tournee de 90 degres.
    result = process_image(_jpeg_with_exif(size=(300, 200), orientation=6), max_dimension=1600)
    assert _open(result.image).size == (200, 300)


def test_process_image_flattens_transparency_on_white(image_file):
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buffer, format="PNG")
    upload = SimpleUploadedFile("t.png", buffer.getvalue())
    output = _open(process_image(upload, max_dimension=100).image).convert("RGB")
    assert output.getpixel((5, 5)) == (255, 255, 255)


def test_process_image_rejects_fake_image(fake_image_file):
    with pytest.raises(ValidationError):
        process_image(fake_image_file, max_dimension=1600)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_sanitize_private_image_keeps_format_and_size(image_file, fmt):
    result = sanitize_private_image(image_file(fmt=fmt, size=(640, 480)))
    output = _open(result)
    assert output.format == fmt
    assert output.size == (640, 480)


def test_sanitize_private_image_removes_metadata():
    output = _open(sanitize_private_image(_jpeg_with_exif()))
    assert not output.getexif()
