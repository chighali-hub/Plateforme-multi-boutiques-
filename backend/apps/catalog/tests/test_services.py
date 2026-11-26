"""Regles metier du catalogue, sans HTTP (services des categories)."""

from unittest import mock

import pytest
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError

from apps.catalog import services
from apps.catalog.models import Category, Product
from apps.catalog.tests.factories import CategoryFactory, ProductFactory
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
