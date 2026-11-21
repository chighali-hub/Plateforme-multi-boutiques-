import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.exceptions import FileTooLarge
from apps.core.validators import (
    normalize_hex_color,
    normalize_phone,
    validate_image_file,
)


@pytest.mark.parametrize(
    "raw",
    ["36123456", "36 12 34 56", "+22236123456", "0022236123456", "36-12-34-56", "+222 36.12.34.56"],
)
def test_normalize_phone_accepts_common_formats(raw):
    assert normalize_phone(raw) == "36123456"


@pytest.mark.parametrize(
    "raw", ["", None, "16123456", "5612345", "561234567", "3612345a", "+33612345678", "0036123456"]
)
def test_normalize_phone_rejects_invalid_numbers(raw):
    with pytest.raises(ValidationError):
        normalize_phone(raw)


@pytest.mark.parametrize("raw, expected", [("#064e3b", "#064E3B"), (" #D4A52A ", "#D4A52A")])
def test_normalize_hex_color_uppercases(raw, expected):
    assert normalize_hex_color(raw) == expected


@pytest.mark.parametrize("raw", ["064E3B", "#064E3", "#064E3BB", "#GGGGGG", "", None, "red"])
def test_normalize_hex_color_rejects_invalid_values(raw):
    with pytest.raises(ValidationError):
        normalize_hex_color(raw)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_validate_image_file_accepts_supported_formats(image_file, fmt):
    info = validate_image_file(image_file(fmt=fmt, size=(40, 30)))
    assert (info.format, info.width, info.height) == (fmt, 40, 30)


def test_validate_image_file_rejects_fake_image(fake_image_file):
    with pytest.raises(ValidationError) as error:
        validate_image_file(fake_image_file)
    assert error.value.code == "invalid_image"


def test_validate_image_file_rejects_unsupported_real_image():
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="GIF")
    with pytest.raises(ValidationError):
        validate_image_file(SimpleUploadedFile("a.gif", buffer.getvalue()))


def test_validate_image_file_rejects_file_over_size_limit(settings, image_file):
    upload = image_file(size=(20, 20))
    settings.UPLOAD_IMAGE_MAX_BYTES = upload.size - 1
    with pytest.raises(FileTooLarge) as error:
        validate_image_file(upload, field_name="logo")
    assert error.value.status_code == 413
    assert error.value.details == {"field": "logo", "max_bytes": upload.size - 1}


def test_validate_image_file_accepts_file_at_size_limit(settings, image_file):
    upload = image_file(size=(20, 20))
    settings.UPLOAD_IMAGE_MAX_BYTES = upload.size
    assert validate_image_file(upload).format == "JPEG"


def test_validate_image_file_rejects_dimensions_over_limit(settings, image_file):
    settings.UPLOAD_IMAGE_MAX_DIMENSION = 100
    with pytest.raises(ValidationError) as error:
        validate_image_file(image_file(size=(101, 50)))
    assert error.value.code == "image_too_large"


def test_validate_image_file_rewinds_the_file(image_file):
    upload = image_file()
    validate_image_file(upload)
    assert upload.tell() == 0
