"""Regles metier du catalogue, sans HTTP (services des categories)."""

from unittest import mock

import pytest
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.catalog import services
from apps.catalog.models import Category, Product
from apps.catalog.tests.factories import CategoryFactory, ImportJobFactory, ProductFactory
from apps.core.exceptions import LimitReached
from apps.shops.tests.factories import ShopFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    return ShopFactory(active=True)


def test_create_category_strips_names_and_saves(shop):
    category = services.create_category(
        shop, {"name_fr": "  Voiles ", "name_ar": " خمارات ", "sort_order": 3}
    )

    category.refresh_from_db()
    assert (category.shop, category.name_fr, category.name_ar, category.sort_order) == (
        shop,
        "Voiles",
        "خمارات",
        3,
    )


def test_create_category_ignores_unknown_fields(shop, make_shop):
    other = make_shop("ACTIVE")

    category = services.create_category(shop, {"name_fr": "Voiles", "shop": other})

    category.refresh_from_db()
    assert category.shop == shop
    assert not Category.objects.filter(shop=other).exists()


def test_create_category_without_name_raises_validation_error(shop):
    with pytest.raises(ValidationError) as excinfo:
        services.create_category(shop, {"name_fr": " ", "name_ar": ""})

    assert "non_field_errors" in excinfo.value.detail
    assert not Category.objects.filter(shop=shop).exists()


def test_create_category_duplicate_name_different_case_raises_on_field(shop):
    CategoryFactory(shop=shop, name_fr="Voiles", name_ar="خمارات")

    with pytest.raises(ValidationError) as excinfo:
        services.create_category(shop, {"name_fr": "VOILES", "name_ar": "ملاحف"})

    assert set(excinfo.value.detail) == {"name_fr"}


def test_create_category_duplicate_both_names_raises_on_both_fields(shop):
    CategoryFactory(shop=shop, name_fr="Voiles", name_ar="خمارات")

    with pytest.raises(ValidationError) as excinfo:
        services.create_category(shop, {"name_fr": "voiles", "name_ar": "خمارات"})

    assert set(excinfo.value.detail) == {"name_fr", "name_ar"}


def test_create_category_concurrent_duplicate_becomes_validation_error(shop):
    """Course entre le controle et l'insertion : la contrainte UNIQUE tranche."""
    CategoryFactory(shop=shop, name_fr="Voiles")

    with mock.patch.object(services, "_ensure_names_are_unique"):
        with pytest.raises(ValidationError) as excinfo:
            services.create_category(shop, {"name_fr": "voiles"})

    assert set(excinfo.value.detail) == {"name_fr"}
    assert Category.objects.filter(shop=shop).count() == 1


def test_update_category_concurrent_duplicate_arabic_becomes_validation_error(shop):
    CategoryFactory(shop=shop, name_ar="خمارات")
    category = CategoryFactory(shop=shop, name_ar="ملاحف")

    with mock.patch.object(services, "_ensure_names_are_unique"):
        with pytest.raises(ValidationError) as excinfo:
            services.update_category(category, {"name_ar": "خمارات"})

    assert set(excinfo.value.detail) == {"name_ar"}
    category.refresh_from_db()
    assert category.name_ar == "ملاحف"


def test_save_category_other_integrity_error_is_not_hidden(shop):
    with mock.patch.object(services, "_ensure_has_name"):
        with pytest.raises(IntegrityError):
            services.create_category(shop, {"name_fr": "", "name_ar": ""})


def test_create_category_at_limit_raises_limit_reached(shop):
    CategoryFactory.create_batch(services.MAX_CATEGORIES, shop=shop)

    with pytest.raises(LimitReached) as excinfo:
        services.create_category(shop, {"name_fr": "De trop"})

    assert excinfo.value.details == {"limit": 100}
    assert Category.objects.filter(shop=shop).count() == services.MAX_CATEGORIES


def test_update_category_checks_final_state(shop):
    category = CategoryFactory(shop=shop, name_fr="Voiles", name_ar="")

    with pytest.raises(ValidationError):
        services.update_category(category, {"name_fr": ""})

    category.refresh_from_db()
    assert category.name_fr == "Voiles"


def test_update_category_keeps_own_name(shop):
    category = CategoryFactory(shop=shop, name_fr="Voiles", sort_order=0)

    updated = services.update_category(category, {"name_fr": "Voiles", "sort_order": 4})

    assert (updated.name_fr, updated.sort_order) == ("Voiles", 4)


def test_update_category_without_fields_changes_nothing(shop):
    category = CategoryFactory(shop=shop, name_fr="Voiles")

    updated = services.update_category(category, {})

    assert updated.name_fr == "Voiles"


def test_delete_category_sets_products_without_category(shop):
    """RG-32 : les produits sont conserves, sans categorie."""
    category = CategoryFactory(shop=shop)
    kept = CategoryFactory(shop=shop)
    products = ProductFactory.create_batch(2, shop=shop, category=category)
    other = ProductFactory(shop=shop, category=kept)
    category_id = category.pk

    services.delete_category(category)

    assert not Category.objects.filter(pk=category_id).exists()
    assert Product.objects.filter(pk__in=[p.pk for p in products], category=None).count() == 2
    other.refresh_from_db()
    assert other.category == kept


# --- Produits ---------------------------------------------------------------------
def _product_files(settings) -> list:
    root = settings.MEDIA_ROOT / "products"
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


def _create(shop, image_file, **data) -> Product:
    payload = {"name_fr": "Melhfa", "price": 2500, **data}
    return services.create_product_from_data(shop, payload, image_file())


def test_create_product_from_data_import_source_and_job(shop, image_file):
    """Reutilisable par l'import (phase 6) : source et job passes en parametres."""
    job = ImportJobFactory(shop=shop)

    product = services.create_product_from_data(
        shop,
        {"name_ar": "ملحفة", "price": 1200, "status": Product.Status.DRAFT},
        image_file(),
        source=Product.Source.IMPORT,
        import_job=job,
    )

    product.refresh_from_db()
    assert (product.source, product.import_job, product.status) == ("IMPORT", job, "DRAFT")
    assert product.published_at is None


def test_create_product_from_data_published_sets_published_at(shop, image_file):
    product = _create(shop, image_file)

    assert product.status == Product.Status.PUBLISHED
    assert product.published_at is not None


def test_create_product_from_data_ignores_protected_keys(shop, image_file, make_shop):
    other = make_shop("ACTIVE")

    product = services.create_product_from_data(
        shop,
        {"name_fr": "Melhfa", "price": 1, "shop": other, "source": "IMPORT", "published_at": None},
        image_file(),
    )

    product.refresh_from_db()
    assert (product.shop, product.source) == (shop, "MANUAL")


def test_create_product_from_data_with_other_shop_category_raises(shop, image_file, settings):
    foreign = CategoryFactory()

    with pytest.raises(ValidationError) as excinfo:
        _create(shop, image_file, category=foreign)

    assert set(excinfo.value.detail) == {"category_id"}
    assert not Product.objects.exists()
    assert _product_files(settings) == []


def test_create_product_from_data_at_limit_raises_before_image(shop, settings):
    Product.objects.bulk_create(
        Product(shop=shop, name_fr=f"P{i}", price=1, image="p.webp", thumbnail="t.webp")
        for i in range(services.MAX_PRODUCTS)
    )
    image = mock.Mock()

    with mock.patch.object(services, "process_product_image") as process:
        with pytest.raises(LimitReached) as excinfo:
            services.create_product_from_data(shop, {"name_fr": "X", "price": 1}, image)

    assert excinfo.value.details == {"limit": 5000}
    process.assert_not_called()


def test_create_product_from_data_invalid_image_raises_on_image_field(shop, fake_image_file):
    with pytest.raises(ValidationError) as excinfo:
        services.create_product_from_data(shop, {"name_fr": "X", "price": 1}, fake_image_file)

    assert set(excinfo.value.detail) == {"image"}


def test_create_product_failure_after_processing_leaves_no_orphan_file(shop, image_file, settings):
    with mock.patch.object(Product, "save", side_effect=RuntimeError("panne")):
        with pytest.raises(RuntimeError):
            _create(shop, image_file)

    assert not Product.objects.exists()
    assert _product_files(settings) == []


def test_update_product_failure_after_processing_keeps_old_files_only(
    shop, image_file, settings, django_capture_on_commit_callbacks
):
    product = _create(shop, image_file)
    before = sorted(_product_files(settings))

    with django_capture_on_commit_callbacks(execute=True):
        with mock.patch.object(Product, "save", side_effect=RuntimeError("panne")):
            with pytest.raises(RuntimeError):
                services.update_product(product, {}, image_file())

    assert sorted(_product_files(settings)) == before
    product.refresh_from_db()
    stored = {path.relative_to(settings.MEDIA_ROOT).as_posix() for path in before}
    assert {product.image.name, product.thumbnail.name} == stored


def test_update_product_rolled_back_transaction_deletes_no_file(
    shop, image_file, settings, django_capture_on_commit_callbacks
):
    product = _create(shop, image_file)
    old_files = {product.image.name, product.thumbnail.name}

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            services.update_product(product, {}, image_file())
            raise RuntimeError("annulation")

    assert callbacks == []
    for name in old_files:
        assert default_storage.exists(name)
    product.refresh_from_db()
    assert {product.image.name, product.thumbnail.name} == old_files


def test_update_product_new_image_deletes_old_files_after_commit(
    shop, image_file, django_capture_on_commit_callbacks
):
    product = _create(shop, image_file)
    old_files = [product.image.name, product.thumbnail.name]

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        updated = services.update_product(product, {}, image_file("PNG"))
        for name in old_files:
            assert default_storage.exists(name)

    for callback in callbacks:
        callback()
    for name in old_files:
        assert not default_storage.exists(name)
    assert default_storage.exists(updated.image.name)
    assert default_storage.exists(updated.thumbnail.name)


def test_update_product_republished_sets_new_published_at(shop, image_file):
    product = _create(shop, image_file)
    first = product.published_at
    services.update_product(product, {"status": Product.Status.DRAFT})

    republished = services.update_product(product, {"status": Product.Status.PUBLISHED})

    assert republished.published_at is not None
    assert republished.published_at >= first


def test_update_product_ignores_protected_keys(shop, image_file):
    product = _create(shop, image_file)

    updated = services.update_product(product, {"source": "IMPORT", "shop": None, "price": 9})

    updated.refresh_from_db()
    assert (updated.source, updated.shop, updated.price) == ("MANUAL", shop, 9)


def test_delete_product_removes_row_and_files_after_commit(
    shop, image_file, settings, django_capture_on_commit_callbacks
):
    product = _create(shop, image_file)
    product_id = product.pk

    with django_capture_on_commit_callbacks(execute=True):
        services.delete_product(product)

    assert not Product.objects.filter(pk=product_id).exists()
    assert _product_files(settings) == []
