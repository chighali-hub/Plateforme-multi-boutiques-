import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import Category, ImportJob, Product, product_search_texts
from apps.catalog.tests.factories import (
    CategoryFactory,
    ImportErrorRowFactory,
    ImportJobFactory,
    ProductFactory,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("price", [0, -1, 100_000_001])
def test_product_price_outside_range_is_refused(price):
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductFactory(price=price)


@pytest.mark.parametrize("price", [1, 100_000_000])
def test_product_price_bounds_are_accepted(price):
    assert ProductFactory(price=price).pk


def test_product_without_any_name_is_refused():
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductFactory(name_fr="", name_ar="")


@pytest.mark.parametrize(
    "names", [{"name_fr": "Voile", "name_ar": ""}, {"name_fr": "", "name_ar": "خمار"}]
)
def test_product_with_one_name_is_accepted(names):
    assert ProductFactory(**names).pk


def test_product_invalid_status_is_refused():
    product = ProductFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Product.objects.filter(pk=product.pk).update(status="ARCHIVED")


def test_product_search_texts_fall_back_on_other_name():
    assert product_search_texts("", "خمار", "Voile noir", "") == ("خمار voile noir", "خمار")
    assert product_search_texts("Melhfa", "", "", "ملحفة") == ("melhfa", "melhfa ملحفه")


def test_product_search_texts_kept_in_sync_on_partial_update():
    product = ProductFactory(name_fr="Ancien", description_fr="")
    product.name_fr = "Téléphone"
    product.save(update_fields=["name_fr"])
    product.refresh_from_db()
    assert product.search_text_fr == "telefone"


def test_category_needs_a_name():
    with pytest.raises(IntegrityError), transaction.atomic():
        CategoryFactory(name_fr="", name_ar="")


def test_category_names_unique_per_shop_ignoring_case():
    category = CategoryFactory(name_fr="Voiles", name_ar="")
    with pytest.raises(IntegrityError), transaction.atomic():
        CategoryFactory(shop=category.shop, name_fr="VOILES", name_ar="")


def test_category_arabic_name_unique_per_shop():
    category = CategoryFactory(name_fr="", name_ar="ملاحف")
    with pytest.raises(IntegrityError), transaction.atomic():
        CategoryFactory(shop=category.shop, name_fr="", name_ar="ملاحف")


def test_category_same_name_allowed_in_another_shop_and_empty_names_not_unique():
    category = CategoryFactory(name_fr="Voiles", name_ar="")
    CategoryFactory(name_fr="Voiles", name_ar="")
    CategoryFactory(shop=category.shop, name_fr="", name_ar="أحذية")
    CategoryFactory(shop=category.shop, name_fr="", name_ar="عطور")
    assert Category.objects.filter(shop=category.shop).count() == 3


def test_deleting_category_keeps_its_products():
    product = ProductFactory(category=CategoryFactory())
    product.category.delete()
    product.refresh_from_db()
    assert product.category is None


def test_only_one_active_import_per_shop():
    job = ImportJobFactory(status=ImportJob.Status.PROCESSING)
    with pytest.raises(IntegrityError), transaction.atomic():
        ImportJobFactory(shop=job.shop, status=ImportJob.Status.PENDING)


def test_finished_imports_do_not_block_a_new_one():
    job = ImportJobFactory(status=ImportJob.Status.COMPLETED)
    ImportJobFactory(shop=job.shop, status=ImportJob.Status.FAILED)
    assert ImportJobFactory(shop=job.shop).status == ImportJob.Status.PENDING


def test_deleting_import_job_detaches_products_and_removes_error_rows():
    row = ImportErrorRowFactory()
    product = ProductFactory(shop=row.shop, import_job=row.job, source=Product.Source.IMPORT)
    row.job.delete()
    product.refresh_from_db()
    assert product.import_job is None
    assert not row.__class__.objects.filter(pk=row.pk).exists()
