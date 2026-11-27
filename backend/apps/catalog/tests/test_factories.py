"""Coherence des fabriques du catalogue avec les regles metier (RG-31)."""

from datetime import UTC, datetime

import pytest

from apps.catalog.models import Product
from apps.catalog.tests.factories import ProductFactory

pytestmark = pytest.mark.django_db


def test_product_factory_published_by_default_has_published_at():
    product = ProductFactory()

    product.refresh_from_db()
    assert product.status == Product.Status.PUBLISHED
    assert product.published_at is not None


def test_product_factory_draft_has_no_published_at():
    product = ProductFactory(status=Product.Status.DRAFT)

    product.refresh_from_db()
    assert product.published_at is None


@pytest.mark.parametrize("status", [Product.Status.PUBLISHED, Product.Status.DRAFT])
def test_product_factory_explicit_published_at_is_kept(status):
    moment = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)

    product = ProductFactory(status=status, published_at=moment)

    product.refresh_from_db()
    assert product.published_at == moment


def test_product_factory_explicit_null_published_at_is_kept():
    product = ProductFactory(status=Product.Status.PUBLISHED, published_at=None)

    product.refresh_from_db()
    assert product.published_at is None
