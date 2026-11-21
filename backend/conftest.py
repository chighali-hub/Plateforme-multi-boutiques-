"""Fixtures pytest partagees par toutes les applications.

Liste et usage : docs/Documentation-API/06-strategie-de-tests.md section 3.1.
"""

import io
from datetime import datetime
from unittest import mock

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.tests.factories import AdminUserFactory
from apps.shops.tests.factories import BankAccountFactory, ShopFactory

SHOP_STATES = ("ONBOARDING", "PENDING", "REJECTED", "ACTIVE", "EXPIRED", "BLOCKED")


def pytest_collection_modifyitems(config, items):
    """Refuse les tests transactionnels.

    Ils vident les tables en fin de test, y compris les lignes creees par les
    migrations de donnees (parametres, modeles de design) : les tests suivants
    echouent alors selon l'ordre d'execution. Pour transaction.on_commit,
    utiliser la fixture django_capture_on_commit_callbacks.
    """
    offenders = []
    for item in items:
        marker = item.get_closest_marker("django_db")
        transactional = marker is not None and marker.kwargs.get("transaction")
        if transactional or "transactional_db" in getattr(item, "fixturenames", ()):
            offenders.append(item.nodeid)
    if offenders:
        raise pytest.UsageError(
            "Tests transactionnels interdits (voir 06-strategie-de-tests.md 3.1) : "
            + ", ".join(offenders)
        )


@pytest.fixture(autouse=True)
def _isolated_files_and_cache(settings, tmp_path):
    """Chaque test ecrit ses fichiers dans un dossier temporaire et part d'un cache vide."""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private_media"
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def admin_user(db):
    return AdminUserFactory()


@pytest.fixture
def admin_client(admin_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    client.user = admin_user
    return client


@pytest.fixture
def make_shop(db):
    """make_shop(state="ACTIVE", **kwargs) : boutique complete dans l'etat voulu."""

    def _make(state: str = "ACTIVE", **kwargs):
        if state not in SHOP_STATES:
            raise ValueError(f"Etat inconnu : {state}")
        return ShopFactory(**{state.lower(): True}, **kwargs)

    return _make


def _client_for(shop) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=shop.owner)
    client.user = shop.owner
    client.shop = shop
    return client


@pytest.fixture
def make_shop_client(make_shop):
    """make_shop_client(state) : client authentifie pour une nouvelle boutique.

    Une boutique ACTIVE recoit une banque, comme une vraie boutique visible.
    """

    def _make(state: str = "ACTIVE", **kwargs) -> APIClient:
        shop = make_shop(state, **kwargs)
        if state == "ACTIVE":
            BankAccountFactory(shop=shop)
        return _client_for(shop)

    return _make


@pytest.fixture
def shop_client(make_shop_client) -> APIClient:
    return make_shop_client("ACTIVE")


@pytest.fixture
def other_shop_client(make_shop_client) -> APIClient:
    """Seconde boutique active, pour les tests d'isolation."""
    return make_shop_client("ACTIVE")


@pytest.fixture
def image_file():
    """image_file(fmt="JPEG", size=(800, 600), name=None) : vraie image en memoire."""

    def _make(fmt: str = "JPEG", size: tuple[int, int] = (800, 600), name: str | None = None):
        buffer = io.BytesIO()
        mode = "RGBA" if fmt == "PNG" else "RGB"
        Image.new(mode, size, (200, 30, 60)).save(buffer, format=fmt)
        extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(fmt, fmt.lower())
        content_type = {"jpg": "image/jpeg"}.get(extension, f"image/{extension}")
        return SimpleUploadedFile(
            name or f"photo.{extension}", buffer.getvalue(), content_type=content_type
        )

    return _make


@pytest.fixture
def fake_image_file():
    """Fichier texte renomme en .jpg : doit etre refuse."""
    return SimpleUploadedFile("photo.jpg", b"<?php echo 'x'; ?>", content_type="image/jpeg")


@pytest.fixture
def freeze_now():
    """freeze_now(datetime) fige django.utils.timezone.now jusqu'a la fin du test."""
    patchers = []

    def _freeze(moment: datetime) -> datetime:
        if timezone.is_naive(moment):
            raise ValueError("freeze_now attend une date avec fuseau.")
        patcher = mock.patch("django.utils.timezone.now", return_value=moment)
        patcher.start()
        patchers.append(patcher)
        return moment

    yield _freeze
    for patcher in reversed(patchers):
        patcher.stop()
