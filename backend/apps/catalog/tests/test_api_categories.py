"""Endpoints des categories de l'espace boutique (03-reference-api.md section 6)."""

import pytest

from apps.catalog.models import Category, Product
from apps.catalog.services import MAX_CATEGORIES
from apps.catalog.tests.factories import CategoryFactory, ProductFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/shop/categories/"
LIST_MAX_QUERIES = 2


def detail_url(category_id: int) -> str:
    return f"/api/v1/shop/categories/{category_id}/"


def error_code(response) -> str:
    return response.json()["error"]["code"]


# --- Cas nominaux ------------------------------------------------------------------
def test_list_categories_returns_shop_categories_sorted(shop_client):
    shop = shop_client.shop
    third = CategoryFactory(shop=shop, name_fr="Accessoires", sort_order=2)
    second_b = CategoryFactory(shop=shop, name_fr="Voiles", sort_order=1)
    second_a = CategoryFactory(shop=shop, name_fr="Melhfas", sort_order=1)
    first = CategoryFactory(shop=shop, name_fr="Zebda", sort_order=0)

    response = shop_client.get(LIST_URL)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        first.id,
        second_a.id,
        second_b.id,
        third.id,
    ]


def test_list_categories_same_sort_order_and_name_is_ordered_by_id(shop_client):
    older = CategoryFactory(shop=shop_client.shop, name_fr="", name_ar="أ", sort_order=0)
    newer = CategoryFactory(shop=shop_client.shop, name_fr="", name_ar="ب", sort_order=0)

    response = shop_client.get(LIST_URL)

    assert [item["id"] for item in response.json()] == [older.id, newer.id]


def test_list_categories_returns_reference_fields_and_products_count(shop_client):
    category = CategoryFactory(shop=shop_client.shop, name_fr="Melhfas", name_ar="ملاحف")
    ProductFactory.create_batch(3, shop=shop_client.shop, category=category)
    ProductFactory(shop=shop_client.shop, category=category, status=Product.Status.DRAFT)
    empty = CategoryFactory(shop=shop_client.shop)

    response = shop_client.get(LIST_URL)

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()}
    assert set(by_id[category.id]) == {
        "id",
        "name_fr",
        "name_ar",
        "sort_order",
        "products_count",
        "created_at",
    }
    assert by_id[category.id]["name_ar"] == "ملاحف"
    assert by_id[category.id]["products_count"] == 4
    assert by_id[empty.id]["products_count"] == 0


def test_list_categories_is_not_paginated(shop_client):
    CategoryFactory.create_batch(25, shop=shop_client.shop)

    response = shop_client.get(LIST_URL)

    assert isinstance(response.json(), list)
    assert len(response.json()) == 25


def test_create_category_returns_201_with_category(shop_client):
    payload = {"name_fr": "Voiles", "name_ar": "خمارات", "sort_order": 1}

    response = shop_client.post(LIST_URL, payload, format="json")

    assert response.status_code == 201
    body = response.json()
    assert body["name_fr"] == "Voiles"
    assert body["name_ar"] == "خمارات"
    assert body["sort_order"] == 1
    assert body["products_count"] == 0
    category = Category.objects.get(pk=body["id"])
    assert category.shop == shop_client.shop


def test_create_category_with_only_arabic_name_is_accepted(shop_client):
    response = shop_client.post(LIST_URL, {"name_ar": "خمارات"}, format="json")

    assert response.status_code == 201
    assert response.json()["name_fr"] == ""
    assert response.json()["sort_order"] == 0


def test_create_category_strips_names(shop_client):
    response = shop_client.post(LIST_URL, {"name_fr": "  Voiles  "}, format="json")

    assert response.status_code == 201
    assert Category.objects.get(pk=response.json()["id"]).name_fr == "Voiles"


def test_create_category_ignores_shop_from_body(shop_client, other_shop_client):
    payload = {"name_fr": "Voiles", "shop": other_shop_client.shop.id}

    response = shop_client.post(LIST_URL, payload, format="json")

    assert response.status_code == 201
    assert Category.objects.get(pk=response.json()["id"]).shop == shop_client.shop
    assert not Category.objects.filter(shop=other_shop_client.shop).exists()


def test_update_category_returns_200_with_products_count(shop_client):
    category = CategoryFactory(shop=shop_client.shop, name_fr="Voiles", sort_order=0)
    ProductFactory.create_batch(2, shop=shop_client.shop, category=category)

    response = shop_client.patch(
        detail_url(category.id), {"name_fr": "Voiles légers", "sort_order": 5}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["name_fr"] == "Voiles légers"
    assert response.json()["sort_order"] == 5
    assert response.json()["products_count"] == 2
    category.refresh_from_db()
    assert (category.name_fr, category.sort_order) == ("Voiles légers", 5)


def test_update_category_with_same_name_different_case_is_accepted(shop_client):
    category = CategoryFactory(shop=shop_client.shop, name_fr="voiles")

    response = shop_client.patch(detail_url(category.id), {"name_fr": "Voiles"}, format="json")

    assert response.status_code == 200
    category.refresh_from_db()
    assert category.name_fr == "Voiles"


def test_update_category_ignores_shop_from_body(shop_client, other_shop_client):
    category = CategoryFactory(shop=shop_client.shop)

    response = shop_client.patch(
        detail_url(category.id), {"shop": other_shop_client.shop.id}, format="json"
    )

    assert response.status_code == 200
    category.refresh_from_db()
    assert category.shop == shop_client.shop


def test_delete_category_returns_204(shop_client):
    category = CategoryFactory(shop=shop_client.shop)

    response = shop_client.delete(detail_url(category.id))

    assert response.status_code == 204
    assert not Category.objects.filter(pk=category.id).exists()


def test_delete_category_with_products_keeps_products_uncategorized(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    products = ProductFactory.create_batch(3, shop=shop_client.shop, category=category)

    response = shop_client.delete(detail_url(category.id))

    assert response.status_code == 204
    assert Product.objects.filter(pk__in=[p.id for p in products], category=None).count() == 3


def test_update_unknown_category_returns_404(shop_client):
    response = shop_client.patch(detail_url(999_999), {"name_fr": "X"}, format="json")

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


# --- Authentification et role ---------------------------------------------------------
@pytest.mark.parametrize(
    "method, with_category",
    [("get", False), ("post", False), ("patch", True), ("delete", True)],
)
def test_categories_without_authentication_returns_401(api_client, method, with_category):
    category = CategoryFactory() if with_category else None
    url = detail_url(category.id) if category else LIST_URL

    response = getattr(api_client, method)(url, {"name_fr": "Voiles"}, format="json")

    assert response.status_code == 401
    assert error_code(response) == "AUTHENTICATION_REQUIRED"
    if category:
        assert Category.objects.get(pk=category.id).name_fr == category.name_fr


@pytest.mark.parametrize(
    "method, with_category",
    [("get", False), ("post", False), ("patch", True), ("delete", True)],
)
def test_categories_as_admin_returns_403(admin_client, method, with_category):
    category = CategoryFactory() if with_category else None
    url = detail_url(category.id) if category else LIST_URL

    response = getattr(admin_client, method)(url, {"name_fr": "Voiles"}, format="json")

    assert response.status_code == 403
    assert error_code(response) == "PERMISSION_DENIED"
    if category:
        assert Category.objects.filter(pk=category.id, name_fr=category.name_fr).exists()
    else:
        assert not Category.objects.filter(name_fr="Voiles").exists()


# --- Matrice des etats (03-reference-api.md section 0.3) ------------------------------
STATE_CASES = [
    ("ONBOARDING", "SHOP_STATE_FORBIDDEN"),
    ("PENDING", "SHOP_STATE_FORBIDDEN"),
    ("REJECTED", "SHOP_STATE_FORBIDDEN"),
    ("ACTIVE", None),
    ("EXPIRED", "SHOP_EXPIRED"),
    ("BLOCKED", "SHOP_BLOCKED"),
]
ENDPOINT_CASES = [
    ("get", False, 200),
    ("post", False, 201),
    ("patch", True, 200),
    ("delete", True, 204),
]


@pytest.mark.parametrize("state, expected_code", STATE_CASES)
@pytest.mark.parametrize("method, with_category, success_status", ENDPOINT_CASES)
def test_categories_by_shop_state(
    make_shop_client, state, expected_code, method, with_category, success_status
):
    client = make_shop_client(state=state)
    category = CategoryFactory(shop=client.shop, name_fr="Melhfas") if with_category else None
    url = detail_url(category.id) if category else LIST_URL

    response = getattr(client, method)(url, {"name_fr": "Voiles"}, format="json")

    if expected_code is None:
        assert response.status_code == success_status
        return
    assert response.status_code == 403
    assert error_code(response) == expected_code
    assert not Category.objects.filter(shop=client.shop, name_fr="Voiles").exists()
    if category:
        assert Category.objects.filter(pk=category.id, name_fr="Melhfas").exists()


# --- Isolation entre boutiques ----------------------------------------------------------
def test_list_categories_never_shows_other_shop_categories(shop_client, other_shop_client):
    mine = CategoryFactory(shop=shop_client.shop)
    CategoryFactory(shop=other_shop_client.shop)

    response = shop_client.get(LIST_URL)

    assert [item["id"] for item in response.json()] == [mine.id]


def test_shop_cannot_update_other_shop_category_returns_404(shop_client, other_shop_client):
    category = CategoryFactory(shop=other_shop_client.shop, name_fr="Melhfas", sort_order=0)

    response = shop_client.patch(
        detail_url(category.id), {"name_fr": "Piratée", "sort_order": 9}, format="json"
    )

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"
    category.refresh_from_db()
    assert (category.name_fr, category.sort_order) == ("Melhfas", 0)


def test_shop_cannot_delete_other_shop_category_returns_404(shop_client, other_shop_client):
    category = CategoryFactory(shop=other_shop_client.shop)
    product = ProductFactory(shop=other_shop_client.shop, category=category)

    response = shop_client.delete(detail_url(category.id))

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"
    assert Category.objects.filter(pk=category.id).exists()
    product.refresh_from_db()
    assert product.category_id == category.id


def test_products_count_ignores_other_shop_products(shop_client, other_shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    ProductFactory(shop=shop_client.shop, category=category)
    ProductFactory(shop=other_shop_client.shop)

    response = shop_client.get(LIST_URL)

    assert response.json()[0]["products_count"] == 1


# --- Validation -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [{}, {"name_fr": "", "name_ar": ""}, {"name_fr": "   ", "name_ar": "  "}, {"sort_order": 1}],
)
def test_create_category_without_any_name_returns_400(shop_client, payload):
    response = shop_client.post(LIST_URL, payload, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "non_field_errors" in response.json()["error"]["details"]
    assert not Category.objects.filter(shop=shop_client.shop).exists()


def test_update_category_emptying_only_name_returns_400(shop_client):
    category = CategoryFactory(shop=shop_client.shop, name_fr="Voiles", name_ar="")

    response = shop_client.patch(detail_url(category.id), {"name_fr": "  "}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "non_field_errors" in response.json()["error"]["details"]
    category.refresh_from_db()
    assert category.name_fr == "Voiles"


def test_update_category_emptying_one_of_two_names_is_accepted(shop_client):
    category = CategoryFactory(shop=shop_client.shop, name_fr="Voiles", name_ar="خمارات")

    response = shop_client.patch(detail_url(category.id), {"name_fr": ""}, format="json")

    assert response.status_code == 200
    category.refresh_from_db()
    assert (category.name_fr, category.name_ar) == ("", "خمارات")


@pytest.mark.parametrize("field", ["name_fr", "name_ar"])
def test_create_category_with_61_characters_returns_400(shop_client, field):
    response = shop_client.post(LIST_URL, {field: "a" * 61}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert field in response.json()["error"]["details"]
    assert not Category.objects.filter(shop=shop_client.shop).exists()


def test_create_category_with_60_characters_is_accepted(shop_client):
    response = shop_client.post(LIST_URL, {"name_fr": "a" * 60}, format="json")

    assert response.status_code == 201


@pytest.mark.parametrize("value", ["abc", -1, 32_768, None])
def test_create_category_with_invalid_sort_order_returns_400(shop_client, value):
    response = shop_client.post(LIST_URL, {"name_fr": "Voiles", "sort_order": value}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "sort_order" in response.json()["error"]["details"]
    assert not Category.objects.filter(shop=shop_client.shop).exists()


@pytest.mark.parametrize("value", [0, 32_767])
def test_create_category_with_sort_order_bounds_is_accepted(shop_client, value):
    response = shop_client.post(LIST_URL, {"name_fr": "Voiles", "sort_order": value}, format="json")

    assert response.status_code == 201
    assert Category.objects.get(pk=response.json()["id"]).sort_order == value


def test_update_category_with_negative_sort_order_returns_400(shop_client):
    category = CategoryFactory(shop=shop_client.shop, sort_order=3)

    response = shop_client.patch(detail_url(category.id), {"sort_order": -1}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "sort_order" in response.json()["error"]["details"]
    category.refresh_from_db()
    assert category.sort_order == 3


def test_create_category_with_duplicate_french_name_different_case_returns_400(shop_client):
    CategoryFactory(shop=shop_client.shop, name_fr="Voiles")

    response = shop_client.post(LIST_URL, {"name_fr": "voiles"}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "name_fr" in response.json()["error"]["details"]
    assert Category.objects.filter(shop=shop_client.shop).count() == 1


def test_create_category_with_duplicate_arabic_name_returns_400(shop_client):
    CategoryFactory(shop=shop_client.shop, name_fr="Voiles", name_ar="خمارات")

    response = shop_client.post(
        LIST_URL, {"name_fr": "Autres", "name_ar": " خمارات "}, format="json"
    )

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert set(response.json()["error"]["details"]) == {"name_ar"}
    assert Category.objects.filter(shop=shop_client.shop).count() == 1


def test_update_category_with_name_of_another_category_returns_400(shop_client):
    CategoryFactory(shop=shop_client.shop, name_fr="Voiles")
    category = CategoryFactory(shop=shop_client.shop, name_fr="Melhfas")

    response = shop_client.patch(detail_url(category.id), {"name_fr": "VOILES"}, format="json")

    assert response.status_code == 400
    assert "name_fr" in response.json()["error"]["details"]
    category.refresh_from_db()
    assert category.name_fr == "Melhfas"


def test_create_category_same_name_in_two_shops_is_accepted(shop_client, other_shop_client):
    CategoryFactory(shop=other_shop_client.shop, name_fr="Voiles", name_ar="خمارات")

    response = shop_client.post(LIST_URL, {"name_fr": "Voiles", "name_ar": "خمارات"}, format="json")

    assert response.status_code == 201


def test_create_category_with_empty_french_names_in_same_shop_is_accepted(shop_client):
    CategoryFactory(shop=shop_client.shop, name_fr="", name_ar="ملاحف")

    response = shop_client.post(LIST_URL, {"name_fr": "", "name_ar": "خمارات"}, format="json")

    assert response.status_code == 201


# --- Limite de 100 categories -------------------------------------------------------------
def test_create_100th_category_is_accepted(shop_client):
    CategoryFactory.create_batch(MAX_CATEGORIES - 1, shop=shop_client.shop)

    response = shop_client.post(LIST_URL, {"name_fr": "Centième"}, format="json")

    assert response.status_code == 201
    assert Category.objects.filter(shop=shop_client.shop).count() == MAX_CATEGORIES


def test_create_101st_category_returns_409_limit_reached(shop_client):
    CategoryFactory.create_batch(MAX_CATEGORIES, shop=shop_client.shop)

    response = shop_client.post(LIST_URL, {"name_fr": "De trop"}, format="json")

    assert response.status_code == 409
    assert error_code(response) == "LIMIT_REACHED"
    assert response.json()["error"]["details"] == {"limit": 100}
    assert Category.objects.filter(shop=shop_client.shop).count() == MAX_CATEGORIES


def test_category_limit_is_counted_per_shop(shop_client, other_shop_client):
    CategoryFactory.create_batch(MAX_CATEGORIES, shop=other_shop_client.shop)

    response = shop_client.post(LIST_URL, {"name_fr": "Voiles"}, format="json")

    assert response.status_code == 201


# --- Nombre de requetes -------------------------------------------------------------------
@pytest.mark.parametrize("count", [1, 30])
def test_list_categories_query_count_is_constant(shop_client, django_assert_max_num_queries, count):
    for category in CategoryFactory.create_batch(count, shop=shop_client.shop):
        ProductFactory(shop=shop_client.shop, category=category)

    with django_assert_max_num_queries(LIST_MAX_QUERIES):
        response = shop_client.get(LIST_URL)

    assert response.status_code == 200
    assert len(response.json()) == count
