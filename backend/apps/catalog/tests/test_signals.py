"""Signal de suppression des fichiers image d'un produit (04-schema section 9.5)."""

import pytest
from django.core.files.storage import default_storage
from django.db import transaction

from apps.catalog import services
from apps.catalog.models import Product
from apps.shops.tests.factories import ShopFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def product(image_file):
    shop = ShopFactory(active=True)
    return services.create_product_from_data(shop, {"name_fr": "Melhfa", "price": 1}, image_file())


def _files(product: Product) -> list[str]:
    return [product.image.name, product.thumbnail.name]


def test_instance_delete_removes_files_after_commit(product, django_capture_on_commit_callbacks):
    names = _files(product)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        product.delete()
        assert all(default_storage.exists(name) for name in names)

    assert len(callbacks) == 2
    for callback in callbacks:
        callback()
    assert not any(default_storage.exists(name) for name in names)


def test_queryset_delete_removes_files(product, django_capture_on_commit_callbacks):
    names = _files(product)

    with django_capture_on_commit_callbacks(execute=True):
        Product.objects.filter(pk=product.pk).delete()

    assert not any(default_storage.exists(name) for name in names)


def test_rolled_back_delete_keeps_files(product, django_capture_on_commit_callbacks):
    names = _files(product)
    product_id = product.pk

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            product.delete()
            raise RuntimeError("annulation")

    assert callbacks == []
    assert Product.objects.filter(pk=product_id).exists()
    assert all(default_storage.exists(name) for name in names)


def test_delete_with_files_already_removed_does_not_fail(
    product, django_capture_on_commit_callbacks
):
    """Cas du retrait par l'admin, qui supprime deja les fichiers lui-meme."""
    names = _files(product)
    for name in names:
        default_storage.delete(name)

    with django_capture_on_commit_callbacks(execute=True):
        product.delete()

    assert not Product.objects.filter(pk=product.pk).exists()
