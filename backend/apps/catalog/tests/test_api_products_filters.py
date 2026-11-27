"""Recherche, filtres, tri et pagination de GET /shop/products/ (03-reference-api.md section 6)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.catalog.models import Product
from apps.catalog.tests.factories import CategoryFactory, ImportJobFactory, ProductFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/shop/products/"
LIST_MAX_QUERIES = 3
LIST_WITH_CATEGORY_MAX_QUERIES = 4


FILTER_PARAMS = [
    "search",
    "category",
    "uncategorized",
    "status",
    "is_available",
    "source",
    "import_job",
    "min_price",
    "max_price",
    "ordering",
]


def admin_products_url(shop) -> str:
    return f"/api/v1/admin/shops/{shop.id}/products/"


def ids(response) -> list[int]:
    return [item["id"] for item in response.json()["results"]]


def error_code(response) -> str:
    return response.json()["error"]["code"]


def details(response) -> dict:
    return response.json()["error"]["details"]


def make(shop, **kwargs) -> Product:
    kwargs.setdefault("name_fr", "Produit")
    kwargs.setdefault("name_ar", "")
    kwargs.setdefault("description_fr", "")
    return ProductFactory(shop=shop, **kwargs)


# --- Recherche ------------------------------------------------------------------------
def test_search_without_accent_finds_accented_name(shop_client):
    phone = make(shop_client.shop, name_fr="Téléphone Samsung")
    make(shop_client.shop, name_fr="Melhfa bleue")

    response = shop_client.get(LIST_URL, {"search": "telephone"})

    assert response.status_code == 200
    assert ids(response) == [phone.id]


def test_search_is_case_insensitive(shop_client):
    melhfa = make(shop_client.shop, name_fr="melhfa bleue")

    response = shop_client.get(LIST_URL, {"search": "MELHFA"})

    assert ids(response) == [melhfa.id]


@pytest.mark.parametrize(
    "fields",
    [
        {"name_fr": "Voile rouge"},
        {"name_fr": "", "name_ar": "Voile rouge"},
        {"name_fr": "Article", "description_fr": "Un voile rouge"},
        {"name_fr": "Article", "description_ar": "Un voile rouge"},
    ],
)
def test_search_finds_word_in_any_text_field(shop_client, fields):
    found = make(shop_client.shop, **fields)
    make(shop_client.shop, name_fr="Parfum")

    response = shop_client.get(LIST_URL, {"search": "voile"})

    assert ids(response) == [found.id]


@pytest.mark.parametrize("query", ["مَلْحَفَة", "ملحفة"])
def test_search_arabic_with_or_without_diacritics(shop_client, query):
    melhfa = make(shop_client.shop, name_fr="", name_ar="مَلْحَفَة زرقاء")
    make(shop_client.shop, name_fr="", name_ar="عطر")

    response = shop_client.get(LIST_URL, {"search": query})

    assert ids(response) == [melhfa.id]


def test_search_several_words_must_all_match(shop_client):
    both = make(shop_client.shop, name_fr="Melhfa bleue")
    make(shop_client.shop, name_fr="Melhfa rouge")
    make(shop_client.shop, name_fr="Voile bleue")

    response = shop_client.get(LIST_URL, {"search": "bleue melhfa"})

    assert ids(response) == [both.id]


@pytest.mark.parametrize("query", ["!!!", "a", "  ", "- é ?"])
def test_search_reduced_to_nothing_is_ignored(shop_client, query):
    products = [make(shop_client.shop, name_fr=f"Produit {i}") for i in range(2)]

    response = shop_client.get(LIST_URL, {"search": query})

    assert response.status_code == 200
    assert sorted(ids(response)) == sorted(p.id for p in products)


def test_search_one_letter_words_are_ignored(shop_client):
    melhfa = make(shop_client.shop, name_fr="Melhfa")

    response = shop_client.get(LIST_URL, {"search": "x melhfa"})

    assert ids(response) == [melhfa.id]


def test_search_only_first_five_words_are_used(shop_client):
    melhfa = make(shop_client.shop, name_fr="aa bb cc dd ee")

    response = shop_client.get(LIST_URL, {"search": "aa bb cc dd ee zz"})

    assert ids(response) == [melhfa.id]


def test_search_with_101_characters_returns_400(shop_client):
    response = shop_client.get(LIST_URL, {"search": "a" * 101})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "search" in details(response)


def test_search_with_100_characters_is_accepted(shop_client):
    response = shop_client.get(LIST_URL, {"search": "a" * 100})

    assert response.status_code == 200


# --- Categorie ------------------------------------------------------------------------
def test_filter_category_returns_its_products(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    inside = make(shop_client.shop, category=category)
    make(shop_client.shop, category=CategoryFactory(shop=shop_client.shop))
    make(shop_client.shop, category=None)

    response = shop_client.get(LIST_URL, {"category": category.id})

    assert ids(response) == [inside.id]


def test_filter_category_of_other_shop_returns_400(shop_client, other_shop_client):
    foreign = CategoryFactory(shop=other_shop_client.shop)
    make(other_shop_client.shop, category=foreign)

    response = shop_client.get(LIST_URL, {"category": foreign.id})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "category" in details(response)


def test_filter_unknown_category_returns_same_error_as_other_shop(shop_client, other_shop_client):
    foreign = CategoryFactory(shop=other_shop_client.shop)

    unknown = shop_client.get(LIST_URL, {"category": 999_999})
    other = shop_client.get(LIST_URL, {"category": foreign.id})

    assert unknown.status_code == other.status_code == 400
    assert details(unknown) == details(other)


@pytest.mark.parametrize("value", ["abc", "1.5", "-1"])
def test_filter_category_not_integer_returns_400(shop_client, value):
    response = shop_client.get(LIST_URL, {"category": value})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "category" in details(response)


def test_filter_uncategorized_returns_products_without_category(shop_client):
    alone = make(shop_client.shop, category=None)
    make(shop_client.shop, category=CategoryFactory(shop=shop_client.shop))

    response = shop_client.get(LIST_URL, {"uncategorized": "true"})

    assert ids(response) == [alone.id]


def test_filter_category_and_uncategorized_together_returns_empty_list(shop_client):
    """Comme l'admin : les deux conditions s'appliquent (ET), aucun produit ne les remplit."""
    category = CategoryFactory(shop=shop_client.shop)
    make(shop_client.shop, category=category)
    make(shop_client.shop, category=None)

    response = shop_client.get(LIST_URL, {"category": category.id, "uncategorized": "true"})

    assert response.status_code == 200
    assert ids(response) == []


# --- Valeurs enumerees ------------------------------------------------------------------
@pytest.mark.parametrize(
    "param, value",
    [
        ("uncategorized", "false"),
        ("uncategorized", "1"),
        ("status", "XXX"),
        ("status", "draft"),
        ("is_available", "yes"),
        ("is_available", "True"),
        ("is_available", "1"),
        ("source", "EXCEL"),
        ("ordering", "xxx"),
        ("ordering", "id"),
        ("ordering", "price,-created_at"),
    ],
)
def test_filter_with_invalid_value_returns_400(shop_client, param, value):
    response = shop_client.get(LIST_URL, {param: value})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert param in details(response)


@pytest.mark.parametrize("param", FILTER_PARAMS)
def test_filter_with_blank_value_is_ignored(shop_client, param):
    """Comme l'admin : `?status=` n'applique aucun filtre."""
    product = make(shop_client.shop, category=CategoryFactory(shop=shop_client.shop))

    response = shop_client.get(f"{LIST_URL}?{param}=")

    assert response.status_code == 200
    assert ids(response) == [product.id]


def test_filter_status_returns_matching_products(shop_client):
    draft = make(shop_client.shop, status=Product.Status.DRAFT)
    make(shop_client.shop, status=Product.Status.PUBLISHED)

    response = shop_client.get(LIST_URL, {"status": "DRAFT"})

    assert ids(response) == [draft.id]


@pytest.mark.parametrize("value, expected", [("true", True), ("false", False)])
def test_filter_is_available_returns_matching_products(shop_client, value, expected):
    available = make(shop_client.shop, is_available=True)
    hidden = make(shop_client.shop, is_available=False)

    response = shop_client.get(LIST_URL, {"is_available": value})

    assert ids(response) == [available.id if expected else hidden.id]


def test_filter_source_returns_matching_products(shop_client):
    imported = make(shop_client.shop, source=Product.Source.IMPORT)
    make(shop_client.shop, source=Product.Source.MANUAL)

    response = shop_client.get(LIST_URL, {"source": "IMPORT"})

    assert ids(response) == [imported.id]


# --- Import -------------------------------------------------------------------------------
def test_filter_import_list_1_returns_only_drafts_of_this_job(shop_client):
    job = ImportJobFactory(shop=shop_client.shop)
    other_job = ImportJobFactory(shop=shop_client.shop, status="COMPLETED")
    draft = make(shop_client.shop, import_job=job, source="IMPORT", status="DRAFT")
    make(shop_client.shop, import_job=job, source="IMPORT", status="PUBLISHED")
    make(shop_client.shop, import_job=other_job, source="IMPORT", status="DRAFT")
    make(shop_client.shop, status="DRAFT")

    response = shop_client.get(LIST_URL, {"status": "DRAFT", "import_job": job.id})

    assert ids(response) == [draft.id]


def test_filter_import_job_of_other_shop_returns_empty_list(shop_client, other_shop_client):
    """Comme l'admin : identifiant valide mais sans produit de la boutique -> liste vide."""
    foreign_job = ImportJobFactory(shop=other_shop_client.shop)
    make(other_shop_client.shop, import_job=foreign_job, source="IMPORT")
    make(shop_client.shop)

    response = shop_client.get(LIST_URL, {"import_job": foreign_job.id})

    assert response.status_code == 200
    assert ids(response) == []


@pytest.mark.parametrize("value", ["abc", "0", "-3", "1.5"])
def test_filter_import_job_invalid_returns_400(shop_client, value):
    response = shop_client.get(LIST_URL, {"import_job": value})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "import_job" in details(response)


# --- Prix -----------------------------------------------------------------------------------
def test_filter_price_bounds_are_inclusive(shop_client):
    below = make(shop_client.shop, price=999)
    at_min = make(shop_client.shop, price=1000)
    inside = make(shop_client.shop, price=1500)
    at_max = make(shop_client.shop, price=2000)
    above = make(shop_client.shop, price=2001)

    response = shop_client.get(
        LIST_URL, {"min_price": 1000, "max_price": 2000, "ordering": "price"}
    )

    assert ids(response) == [at_min.id, inside.id, at_max.id]
    assert below.id not in ids(response) and above.id not in ids(response)


def test_filter_min_price_alone(shop_client):
    make(shop_client.shop, price=100)
    kept = make(shop_client.shop, price=500)

    response = shop_client.get(LIST_URL, {"min_price": 500})

    assert ids(response) == [kept.id]


def test_filter_max_price_alone(shop_client):
    kept = make(shop_client.shop, price=100)
    make(shop_client.shop, price=500)

    response = shop_client.get(LIST_URL, {"max_price": 100})

    assert ids(response) == [kept.id]


def test_filter_min_price_equal_max_price_is_accepted(shop_client):
    exact = make(shop_client.shop, price=2500)
    make(shop_client.shop, price=2501)

    response = shop_client.get(LIST_URL, {"min_price": 2500, "max_price": 2500})

    assert response.status_code == 200
    assert ids(response) == [exact.id]


def test_filter_min_price_greater_than_max_price_returns_400(shop_client):
    response = shop_client.get(LIST_URL, {"min_price": 3000, "max_price": 1000})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert set(details(response)) == {"min_price"}


@pytest.mark.parametrize("param", ["min_price", "max_price"])
@pytest.mark.parametrize("value", ["abc", "-1", "2.5"])
def test_filter_price_invalid_returns_400(shop_client, param, value):
    response = shop_client.get(LIST_URL, {param: value})

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert param in details(response)


def test_filter_price_zero_is_accepted(shop_client):
    product = make(shop_client.shop, price=1)

    response = shop_client.get(LIST_URL, {"min_price": 0})

    assert ids(response) == [product.id]


# --- Filtres combines -------------------------------------------------------------------
def test_combined_filters_category_price_and_search(shop_client):
    """Chaque filtre elimine au moins un produit (06, phase 5)."""
    shop = shop_client.shop
    voiles = CategoryFactory(shop=shop, name_fr="Voiles")
    autres = CategoryFactory(shop=shop, name_fr="Autres")
    kept = make(shop, name_fr="Melhfa bleue", category=voiles, price=2500)
    make(shop, name_fr="Melhfa bleue", category=autres, price=2500)  # categorie
    make(shop, name_fr="Melhfa bleue", category=voiles, price=500)  # min_price
    make(shop, name_fr="Melhfa bleue", category=voiles, price=9000)  # max_price
    make(shop, name_fr="Parfum", category=voiles, price=2500)  # search

    response = shop_client.get(
        LIST_URL,
        {"category": voiles.id, "min_price": 1000, "max_price": 5000, "search": "melhfa"},
    )

    assert response.status_code == 200
    assert ids(response) == [kept.id]


def test_combined_filters_status_availability_and_source(shop_client):
    shop = shop_client.shop
    kept = make(shop, status="PUBLISHED", is_available=False, source="MANUAL")
    make(shop, status="DRAFT", is_available=False, source="MANUAL")
    make(shop, status="PUBLISHED", is_available=True, source="MANUAL")
    make(shop, status="PUBLISHED", is_available=False, source="IMPORT")

    response = shop_client.get(
        LIST_URL, {"status": "PUBLISHED", "is_available": "false", "source": "MANUAL"}
    )

    assert ids(response) == [kept.id]


# --- Tri --------------------------------------------------------------------------------------
@pytest.fixture
def sortable(shop_client):
    """Trois produits : deux au meme prix (departage par id), dates distinctes."""
    shop = shop_client.shop
    now = timezone.now()
    first = make(shop, name_fr="Bravo", price=300)
    second = make(shop, name_fr="Alpha", price=100)
    third = make(shop, name_fr="Charlie", price=100)
    for offset, product in enumerate((first, second, third)):
        Product.objects.filter(pk=product.pk).update(created_at=now + timedelta(minutes=offset))
    return first, second, third


@pytest.mark.parametrize(
    "ordering, expected",
    [
        (None, (2, 1, 0)),
        ("-created_at", (2, 1, 0)),
        ("created_at", (0, 1, 2)),
        ("price", (1, 2, 0)),
        ("-price", (0, 2, 1)),
        ("name_fr", (1, 0, 2)),
        ("-name_fr", (2, 0, 1)),
    ],
)
def test_ordering_values_sort_with_id_tiebreak(shop_client, sortable, ordering, expected):
    params = {"ordering": ordering} if ordering else {}

    response = shop_client.get(LIST_URL, params)

    assert response.status_code == 200
    assert ids(response) == [sortable[index].id for index in expected]


def test_ordering_same_created_at_uses_id(shop_client):
    now = timezone.now()
    products = [make(shop_client.shop) for _ in range(3)]
    Product.objects.filter(pk__in=[p.pk for p in products]).update(created_at=now)

    newest_first = shop_client.get(LIST_URL)
    oldest_first = shop_client.get(LIST_URL, {"ordering": "created_at"})

    assert ids(newest_first) == [p.id for p in reversed(products)]
    assert ids(oldest_first) == [p.id for p in products]


# --- Pagination ----------------------------------------------------------------------------
def test_pagination_second_page(shop_client):
    products = [make(shop_client.shop) for _ in range(5)]

    response = shop_client.get(LIST_URL, {"page": 2, "page_size": 2, "ordering": "created_at"})

    assert response.status_code == 200
    assert response.json()["count"] == 5
    assert ids(response) == [products[2].id, products[3].id]


def test_pagination_out_of_range_page_returns_404(shop_client):
    make(shop_client.shop)

    response = shop_client.get(LIST_URL, {"page": 3})

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_pagination_page_size_is_capped_at_100(shop_client):
    ProductFactory.create_batch(105, shop=shop_client.shop)

    response = shop_client.get(LIST_URL, {"page_size": 200})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 100
    assert response.json()["count"] == 105


def test_pagination_keeps_filters_in_next_link(shop_client):
    for _ in range(3):
        make(shop_client.shop, status="DRAFT")

    response = shop_client.get(LIST_URL, {"status": "DRAFT", "page_size": 2})

    assert "status=DRAFT" in response.json()["next"]


# --- Isolation -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"search": "melhfa"},
        {"status": "PUBLISHED"},
        {"source": "IMPORT"},
        {"uncategorized": "true"},
        {"min_price": 0, "max_price": 100000000},
        {"ordering": "price"},
    ],
)
def test_filters_never_return_other_shop_products(shop_client, other_shop_client, params):
    mine = make(shop_client.shop, name_fr="Melhfa", source="IMPORT", category=None)
    make(other_shop_client.shop, name_fr="Melhfa", source="IMPORT", category=None)

    response = shop_client.get(LIST_URL, params)

    assert ids(response) == [mine.id]


# --- Nombre de requetes --------------------------------------------------------------------
@pytest.mark.parametrize("count", [1, 30])
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"search": "melhfa", "min_price": 1, "max_price": 5000, "ordering": "-price"},
        {"status": "PUBLISHED", "is_available": "true", "source": "MANUAL"},
    ],
)
def test_list_query_count_is_constant(shop_client, django_assert_max_num_queries, count, params):
    category = CategoryFactory(shop=shop_client.shop)
    ProductFactory.create_batch(count, shop=shop_client.shop, category=category, name_fr="Melhfa")

    with django_assert_max_num_queries(LIST_MAX_QUERIES):
        response = shop_client.get(LIST_URL, {**params, "page_size": 50})

    assert len(response.json()["results"]) == count


@pytest.mark.parametrize("count", [1, 30])
def test_list_query_count_with_category_filter_is_constant(
    shop_client, django_assert_max_num_queries, count
):
    """Le filtre `category` ajoute une seule requete (controle de la categorie)."""
    category = CategoryFactory(shop=shop_client.shop)
    ProductFactory.create_batch(count, shop=shop_client.shop, category=category)

    with django_assert_max_num_queries(LIST_WITH_CATEGORY_MAX_QUERIES):
        response = shop_client.get(LIST_URL, {"category": category.id, "page_size": 50})

    assert len(response.json()["results"]) == count


# --- Coherence avec l'admin (GET /admin/shops/{id}/products/) ---------------------------------
@pytest.mark.parametrize(
    "params",
    [
        {"min_price": "abc"},
        {"min_price": 3000, "max_price": 1000},
        {"status": "XXX"},
        {"is_available": "yes"},
        {"ordering": "xxx"},
        {"import_job": "0"},
        {"search": "a" * 101},
        {"uncategorized": "false"},
        {"source": "EXCEL"},
        {"max_price": "-1"},
        {"category": "abc"},
    ],
)
def test_invalid_filters_same_error_as_admin(shop_client, admin_client, params):
    shop_response = shop_client.get(LIST_URL, params)
    admin_response = admin_client.get(admin_products_url(shop_client.shop), params)

    assert shop_response.status_code == admin_response.status_code == 400
    assert error_code(shop_response) == error_code(admin_response) == "VALIDATION_ERROR"
    assert set(details(shop_response)) == set(details(admin_response))


@pytest.mark.parametrize("param", FILTER_PARAMS)
def test_blank_filters_ignored_like_admin(shop_client, admin_client, param):
    make(shop_client.shop)

    shop_response = shop_client.get(f"{LIST_URL}?{param}=")
    admin_response = admin_client.get(f"{admin_products_url(shop_client.shop)}?{param}=")

    assert shop_response.status_code == admin_response.status_code == 200
    assert ids(shop_response) == ids(admin_response)


@pytest.mark.parametrize(
    "params",
    [
        {"search": "telephone"},
        {"status": "DRAFT", "ordering": "price"},
        {"min_price": 100, "max_price": 2500, "ordering": "-price"},
        {"uncategorized": "true", "is_available": "true"},
    ],
)
def test_valid_filters_same_results_as_admin(shop_client, admin_client, params):
    shop = shop_client.shop
    make(shop, name_fr="Téléphone", price=2500, status="DRAFT", category=None)
    make(shop, name_fr="Melhfa", price=100, category=CategoryFactory(shop=shop))
    make(shop, name_fr="Parfum", price=9000, is_available=False, category=None)

    shop_response = shop_client.get(LIST_URL, params)
    admin_response = admin_client.get(admin_products_url(shop), params)

    assert shop_response.status_code == admin_response.status_code == 200
    assert ids(shop_response) == ids(admin_response)


def test_unknown_category_differs_from_admin(shop_client, admin_client):
    """Ecart constate (rapport, etape 3) : l'admin ne verifie pas l'existence."""
    shop_response = shop_client.get(LIST_URL, {"category": 999_999})
    admin_response = admin_client.get(admin_products_url(shop_client.shop), {"category": 999_999})

    assert shop_response.status_code == 400
    assert admin_response.status_code == 200
