"""Conventions transverses des endpoints du catalogue : langue des erreurs et debit.

Voir 03-reference-api.md section 0.4 (message traduit selon Accept-Language),
05-aspects-transversaux.md section 7 et 07-securite.md section 6.
"""

import pytest
from rest_framework.views import APIView

from apps.catalog import views
from apps.catalog.tests.factories import CategoryFactory, ProductFactory
from config.settings import base as base_settings

pytestmark = pytest.mark.django_db

CATEGORIES_URL = "/api/v1/shop/categories/"
PRODUCTS_URL = "/api/v1/shop/products/"


def first_detail_message(response) -> str:
    details = response.json()["error"]["details"]
    return next(iter(details.values()))[0]


@pytest.mark.parametrize(
    "language, expected",
    [
        ("fr", "Renseignez au moins un nom, en français ou en arabe."),
        ("ar", "أدخل اسمًا واحدًا على الأقل، بالفرنسية أو بالعربية."),
    ],
)
def test_category_without_name_message_follows_accept_language(shop_client, language, expected):
    response = shop_client.post(CATEGORIES_URL, {}, format="json", HTTP_ACCEPT_LANGUAGE=language)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert first_detail_message(response) == expected


def test_category_duplicate_message_in_arabic(shop_client):
    CategoryFactory(shop=shop_client.shop, name_fr="Voiles")

    response = shop_client.post(
        CATEGORIES_URL, {"name_fr": "voiles"}, format="json", HTTP_ACCEPT_LANGUAGE="ar"
    )

    assert response.status_code == 400
    assert first_detail_message(response) == "توجد فئة بهذا الاسم في متجرك بالفعل."


def test_product_unknown_category_message_in_arabic(shop_client):
    product = ProductFactory(shop=shop_client.shop)

    response = shop_client.patch(
        f"{PRODUCTS_URL}{product.id}/",
        {"category_id": 999_999},
        format="json",
        HTTP_ACCEPT_LANGUAGE="ar",
    )

    assert response.status_code == 400
    assert first_detail_message(response) == "هذه الفئة غير موجودة في متجرك."


def test_bulk_update_without_field_message_in_arabic(shop_client):
    product = ProductFactory(shop=shop_client.shop)

    response = shop_client.post(
        f"{PRODUCTS_URL}bulk-update/",
        {"ids": [product.id]},
        format="json",
        HTTP_ACCEPT_LANGUAGE="ar",
    )

    assert response.status_code == 400
    assert first_detail_message(response) == (
        "حدّد حقلًا واحدًا على الأقل لتعديله: category_id أو is_available."
    )


def test_error_message_header_in_arabic(shop_client):
    response = shop_client.get(PRODUCTS_URL, {"min_price": "abc"}, HTTP_ACCEPT_LANGUAGE="ar")

    assert response.status_code == 400
    assert response.json()["error"]["message"] != "Les données envoyées sont invalides."


@pytest.mark.parametrize(
    "view_class",
    [
        views.CategoryListCreateView,
        views.CategoryDetailView,
        views.ProductListCreateView,
        views.ProductDetailView,
        views.ProductBulkPublishView,
        views.ProductBulkUpdateView,
        views.ProductBulkDeleteView,
    ],
)
def test_catalog_views_keep_default_throttles(view_class):
    """07 section 6 : la limite par defaut des utilisateurs authentifies s'applique.

    Les parametres de test desactivent les limites (config/settings/test.py) ; on
    verifie donc qu'aucune vue du catalogue ne remplace `throttle_classes` et que
    les parametres de base (dev, prod) contiennent bien UserRateThrottle a 300/min.
    """
    overriding = [klass for klass in view_class.__mro__ if "throttle_classes" in vars(klass)]

    assert overriding == [APIView]
    assert (
        "rest_framework.throttling.UserRateThrottle"
        in (base_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"])
    )
    assert base_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["user"] == "300/min"
