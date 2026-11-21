import re
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction

from apps.core.storage import (
    PrivateMediaStorage,
    UploadTo,
    delete_file_on_commit,
    private_file_response,
)
from apps.shops.models import Shop


def test_upload_to_discards_client_filename():
    path = UploadTo("id_cards")(None, "../../etc/passwd-carte.JPG")
    assert re.fullmatch(r"id_cards/\d{4}/\d{2}/[0-9a-f]{32}\.jpg", path)


def test_upload_to_drops_unknown_extension():
    path = UploadTo("products")(None, "script.php")
    assert re.fullmatch(r"products/\d{4}/\d{2}/[0-9a-f]{32}", path)


def test_upload_to_is_deconstructible_for_migrations():
    assert UploadTo("a") == UploadTo("a/")
    assert UploadTo("a") != UploadTo("b")


def test_private_storage_is_outside_media_root_and_has_no_url(settings):
    storage = PrivateMediaStorage()
    assert Path(storage.location) == Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    assert not Path(storage.location).is_relative_to(Path(settings.MEDIA_ROOT).resolve())
    with pytest.raises(ValueError):
        storage.url("id_cards/x.jpg")


def test_id_card_fields_use_private_storage():
    for field_name in ("id_card_front", "id_card_back"):
        assert isinstance(Shop._meta.get_field(field_name).storage, PrivateMediaStorage)
    assert not isinstance(Shop._meta.get_field("logo").storage, PrivateMediaStorage)


@pytest.mark.django_db
def test_private_file_response_sets_protective_headers():
    storage = PrivateMediaStorage()
    name = storage.save("id_cards/test.jpg", ContentFile(b"\xff\xd8contenu"))
    field = Shop._meta.get_field("id_card_front")
    field_file = field.attr_class(None, field, name)

    response = private_file_response(field_file)

    assert response["Content-Type"] == "image/jpeg"
    assert response["Content-Disposition"] == "inline"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert b"".join(response.streaming_content) == b"\xff\xd8contenu"
    response.close()


def _logo_file(name):
    field = Shop._meta.get_field("logo")
    return field.attr_class(None, field, name)


@pytest.mark.django_db
def test_delete_file_on_commit_waits_for_commit(django_capture_on_commit_callbacks):
    name = default_storage.save("products/a.webp", ContentFile(b"x"))

    with django_capture_on_commit_callbacks(execute=True):
        delete_file_on_commit(_logo_file(name))
        assert default_storage.exists(name)
    assert not default_storage.exists(name)


@pytest.mark.django_db
def test_delete_file_on_commit_keeps_file_on_rollback(django_capture_on_commit_callbacks):
    name = default_storage.save("products/b.webp", ContentFile(b"x"))

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            delete_file_on_commit(_logo_file(name))
            raise RuntimeError("echec")
    assert callbacks == []
    assert default_storage.exists(name)


@pytest.mark.django_db
def test_private_webp_is_served_as_image():
    """Sans /etc/mime.types, Python 3.12 ne connait pas .webp : avec nosniff, le
    navigateur refuserait alors d'afficher l'image."""
    storage = PrivateMediaStorage()
    name = storage.save("id_cards/carte.webp", ContentFile(b"RIFF....WEBP"))
    field = Shop._meta.get_field("id_card_front")
    response = private_file_response(field.attr_class(None, field, name))
    assert response["Content-Type"] == "image/webp"
    response.close()
