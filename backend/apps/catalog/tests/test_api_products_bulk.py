"""Actions groupees sur les produits (03-reference-api.md section 6).

bulk-publish, bulk-update, bulk-delete. Pour bulk-update et bulk-delete, les
identifiants inexistants ou d'une autre boutique sont ignores (traitement
partiel, decision du responsable de la phase 5).
"""

import pytest
from django.core.files.storage import default_storage
from django.urls import resolve

from apps.catalog import services
from apps.catalog.models import Product
from apps.catalog.tests.factories import CategoryFactory, ImportJobFactory, ProductFactory
from apps.orders.models import OrderItem
from apps.orders.tests.factories import OrderFactory, OrderItemFactory

pytestmark = pytest.mark.django_db

PUBLISH_URL = "/api/v1/shop/products/bulk-publish/"
LIST_URL = "/api/v1/shop/products/"
PUBLISH_MAX_QUERIES = 5


def error_code(response) -> str:
    return response.json()["error"]["code"]


def details(response) -> dict:
    return response.json()["error"]["details"]


def draft(shop, **kwargs) -> Product:
    return ProductFactory(shop=shop, status=Product.Status.DRAFT, published_at=None, **kwargs)


def snapshot(product: Product) -> tuple:
    product.refresh_from_db()
    return (
        product.status,
        product.published_at,
        product.updated_at,
        product.category_id,
        product.is_available,
        product.search_text_fr,
        product.search_text_ar,
    )


# --- Routes ---------------------------------------------------------------------------
def test_bulk_publish_route_is_not_captured_by_detail_route():
    assert resolve(PUBLISH_URL).url_name == "catalog-products-bulk-publish"
    assert resolve("/api/v1/shop/products/12/").url_name == "catalog-products-detail"


def test_bulk_publish_get_returns_405(shop_client):
    response = shop_client.get(PUBLISH_URL)

    assert response.status_code == 405
    assert error_code(response) == "METHOD_NOT_ALLOWED"


# --- Cas nominal ---------------------------------------------------------------------
def test_bulk_publish_drafts_returns_published_ids(shop_client):
    first, second = draft(shop_client.shop), draft(shop_client.shop)

    response = shop_client.post(PUBLISH_URL, {"ids": [first.id, second.id]}, format="json")

    assert response.status_code == 200
    assert response.json() == {"published_ids": [first.id, second.id], "skipped": []}
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == second.status == Product.Status.PUBLISHED
    assert first.published_at is not None
    assert first.published_at == second.published_at


def test_bulk_publish_updates_updated_at_but_not_texts(shop_client):
    product = draft(shop_client.shop, name_fr="Téléphone")
    before = snapshot(product)

    shop_client.post(PUBLISH_URL, {"ids": [product.id]}, format="json")

    after = snapshot(product)
    assert after[2] > before[2]
    assert after[5:] == before[5:]
    assert product.search_text_fr.startswith("telefone")


def test_bulk_publish_already_published_is_skipped_and_keeps_date(shop_client):
    published = ProductFactory(shop=shop_client.shop, status=Product.Status.PUBLISHED)
    Product.objects.filter(pk=published.pk).update(published_at="2026-01-01T00:00:00+00:00")
    before = snapshot(published)

    response = shop_client.post(PUBLISH_URL, {"ids": [published.id]}, format="json")

    assert response.status_code == 200
    assert response.json() == {
        "published_ids": [],
        "skipped": [{"id": published.id, "reason": "ALREADY_PUBLISHED"}],
    }
    assert snapshot(published) == before


def test_bulk_publish_unavailable_draft_stays_unavailable(shop_client):
    product = draft(shop_client.shop, is_available=False)

    response = shop_client.post(PUBLISH_URL, {"ids": [product.id]}, format="json")

    assert response.json()["published_ids"] == [product.id]
    product.refresh_from_db()
    assert (product.status, product.is_available) == ("PUBLISHED", False)


def test_bulk_publish_keeps_category(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    product = draft(shop_client.shop, category=category)

    shop_client.post(PUBLISH_URL, {"ids": [product.id]}, format="json")

    product.refresh_from_db()
    assert product.category == category


# --- Melange d'identifiants (06, phase 5) ---------------------------------------------
def test_bulk_publish_mixed_ids_follows_request_order(shop_client, other_shop_client):
    shop = shop_client.shop
    mine_draft_a = draft(shop)
    mine_published = ProductFactory(shop=shop, status=Product.Status.PUBLISHED)
    mine_draft_b = draft(shop)
    foreign_draft = draft(other_shop_client.shop)
    foreign_before = snapshot(foreign_draft)
    missing = 999_999
    ids = [
        mine_draft_b.id,
        foreign_draft.id,
        mine_published.id,
        missing,
        mine_draft_a.id,
        mine_draft_b.id,  # doublon : ignore
        foreign_draft.id,  # doublon : ignore
    ]

    response = shop_client.post(PUBLISH_URL, {"ids": ids}, format="json")

    assert response.status_code == 200
    assert response.json() == {
        "published_ids": [mine_draft_b.id, mine_draft_a.id],
        "skipped": [
            {"id": foreign_draft.id, "reason": "NOT_FOUND"},
            {"id": mine_published.id, "reason": "ALREADY_PUBLISHED"},
            {"id": missing, "reason": "NOT_FOUND"},
        ],
    }
    assert snapshot(foreign_draft) == foreign_before
    assert Product.objects.get(pk=foreign_draft.id).status == Product.Status.DRAFT


def test_bulk_publish_other_shop_id_same_reason_as_missing(shop_client, other_shop_client):
    foreign = draft(other_shop_client.shop)

    response = shop_client.post(PUBLISH_URL, {"ids": [foreign.id, 999_999]}, format="json")

    assert [item["reason"] for item in response.json()["skipped"]] == ["NOT_FOUND", "NOT_FOUND"]
    foreign.refresh_from_db()
    assert foreign.status == Product.Status.DRAFT


def test_bulk_publish_only_unknown_ids_returns_200_and_changes_nothing(shop_client):
    product = draft(shop_client.shop)

    response = shop_client.post(PUBLISH_URL, {"ids": [999_998, 999_999]}, format="json")

    assert response.status_code == 200
    assert response.json()["published_ids"] == []
    product.refresh_from_db()
    assert product.status == Product.Status.DRAFT


# --- Liste 1 de l'import ---------------------------------------------------------------
def test_import_list_1_is_empty_after_bulk_publish(shop_client):
    job = ImportJobFactory(shop=shop_client.shop, status="COMPLETED")
    drafts = [draft(shop_client.shop, import_job=job, source="IMPORT") for _ in range(3)]
    params = {"status": "DRAFT", "import_job": job.id}
    listed = [item["id"] for item in shop_client.get(LIST_URL, params).json()["results"]]
    assert sorted(listed) == sorted(p.id for p in drafts)

    response = shop_client.post(PUBLISH_URL, {"ids": listed}, format="json")

    assert response.status_code == 200
    assert sorted(response.json()["published_ids"]) == sorted(listed)
    assert shop_client.get(LIST_URL, params).json()["results"] == []


# --- Validation de ids ---------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"ids": []},
        {"ids": None},
        {"ids": "1,2"},
        {"ids": 5},
        {"ids": {"a": 1}},
        {"ids": [1, "abc"]},
        {"ids": [1.5]},
        {"ids": [0]},
        {"ids": [-4]},
        {"ids": [True]},
        {"ids": list(range(1, 1002))},
    ],
)
def test_bulk_publish_invalid_ids_returns_400(shop_client, payload):
    product = draft(shop_client.shop)

    response = shop_client.post(PUBLISH_URL, payload, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "ids" in details(response)
    product.refresh_from_db()
    assert product.status == Product.Status.DRAFT


def test_bulk_publish_1000_ids_is_accepted(shop_client):
    product = draft(shop_client.shop)
    ids = [product.id, *range(10_000_000, 10_000_999)]

    response = shop_client.post(PUBLISH_URL, {"ids": ids}, format="json")

    assert response.status_code == 200
    assert response.json()["published_ids"] == [product.id]
    assert len(response.json()["skipped"]) == 999


# --- Authentification, role, etats ----------------------------------------------------------
def test_bulk_publish_without_authentication_returns_401(api_client):
    product = draft(ProductFactory().shop)

    response = api_client.post(PUBLISH_URL, {"ids": [product.id]}, format="json")

    assert response.status_code == 401
    assert error_code(response) == "AUTHENTICATION_REQUIRED"
    product.refresh_from_db()
    assert product.status == Product.Status.DRAFT


def test_bulk_publish_as_admin_returns_403(admin_client):
    product = draft(ProductFactory().shop)

    response = admin_client.post(PUBLISH_URL, {"ids": [product.id]}, format="json")

    assert response.status_code == 403
    assert error_code(response) == "PERMISSION_DENIED"
    product.refresh_from_db()
    assert product.status == Product.Status.DRAFT


@pytest.mark.parametrize(
    "state, expected_code",
    [
        ("ONBOARDING", "SHOP_STATE_FORBIDDEN"),
        ("PENDING", "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", "SHOP_STATE_FORBIDDEN"),
        ("ACTIVE", None),
        ("EXPIRED", "SHOP_EXPIRED"),
        ("BLOCKED", "SHOP_BLOCKED"),
    ],
)
def test_bulk_publish_by_shop_state(make_shop_client, state, expected_code):
    client = make_shop_client(state=state)
    product = draft(client.shop)

    response = client.post(PUBLISH_URL, {"ids": [product.id]}, format="json")

    product.refresh_from_db()
    if expected_code is None:
        assert response.status_code == 200
        assert product.status == Product.Status.PUBLISHED
        return
    assert response.status_code == 403
    assert error_code(response) == expected_code
    assert product.status == Product.Status.DRAFT


# --- Nombre de requetes ----------------------------------------------------------------------
@pytest.mark.parametrize("count", [1, 100])
def test_bulk_publish_query_count_is_constant(shop_client, django_assert_max_num_queries, count):
    Product.objects.bulk_create(
        Product(
            shop=shop_client.shop,
            name_fr=f"P{i}",
            price=1,
            image="p.webp",
            thumbnail="t.webp",
            status=Product.Status.DRAFT,
        )
        for i in range(count)
    )
    ids = list(Product.objects.filter(shop=shop_client.shop).values_list("id", flat=True))

    with django_assert_max_num_queries(PUBLISH_MAX_QUERIES):
        response = shop_client.post(PUBLISH_URL, {"ids": ids}, format="json")

    assert len(response.json()["published_ids"]) == count
    assert not Product.objects.filter(shop=shop_client.shop, status="DRAFT").exists()


# ======================================================================================
# bulk-update et bulk-delete : traitement partiel
# ======================================================================================
UPDATE_URL = "/api/v1/shop/products/bulk-update/"
DELETE_URL = "/api/v1/shop/products/bulk-delete/"
UPDATE_MAX_QUERIES = 5


@pytest.fixture
def real_product(image_file):
    """Produit avec de vrais fichiers image (cree par le service)."""

    def _make(shop, **data):
        payload = {"name_fr": "Melhfa", "price": 2500, **data}
        return services.create_product_from_data(shop, payload, image_file())

    return _make


def files_exist(product: Product) -> bool:
    return default_storage.exists(product.image.name) and default_storage.exists(
        product.thumbnail.name
    )


# --- Routes ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url, name",
    [
        (UPDATE_URL, "catalog-products-bulk-update"),
        (DELETE_URL, "catalog-products-bulk-delete"),
    ],
)
def test_bulk_routes_are_not_captured_by_detail_route(shop_client, url, name):
    assert resolve(url).url_name == name

    response = shop_client.get(url)

    assert response.status_code == 405
    assert error_code(response) == "METHOD_NOT_ALLOWED"


# --- bulk-update : cas nominaux ---------------------------------------------------------
def test_bulk_update_category_returns_updated_count(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    products = [ProductFactory(shop=shop_client.shop, category=None) for _ in range(2)]

    response = shop_client.post(
        UPDATE_URL, {"ids": [p.id for p in products], "category_id": category.id}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {"updated_count": 2}
    assert Product.objects.filter(pk__in=[p.id for p in products], category=category).count() == 2


def test_bulk_update_null_category_removes_it(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    product = ProductFactory(shop=shop_client.shop, category=category)

    response = shop_client.post(
        UPDATE_URL, {"ids": [product.id], "category_id": None}, format="json"
    )

    assert response.json() == {"updated_count": 1}
    product.refresh_from_db()
    assert product.category is None


def test_bulk_update_is_available_keeps_category(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    product = ProductFactory(shop=shop_client.shop, category=category, is_available=True)

    response = shop_client.post(
        UPDATE_URL, {"ids": [product.id], "is_available": False}, format="json"
    )

    assert response.json() == {"updated_count": 1}
    product.refresh_from_db()
    assert (product.is_available, product.category) == (False, category)


def test_bulk_update_both_fields(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    product = ProductFactory(shop=shop_client.shop, category=None, is_available=True)

    response = shop_client.post(
        UPDATE_URL,
        {"ids": [product.id], "category_id": category.id, "is_available": False},
        format="json",
    )

    assert response.json() == {"updated_count": 1}
    product.refresh_from_db()
    assert (product.category, product.is_available) == (category, False)


def test_bulk_update_keeps_status_published_at_and_texts_but_updates_updated_at(shop_client):
    draft_product = draft(shop_client.shop, name_fr="Téléphone")
    published = ProductFactory(shop=shop_client.shop, status=Product.Status.PUBLISHED)
    Product.objects.filter(pk=published.pk).update(published_at="2026-01-01T00:00:00+00:00")
    before = {p.id: snapshot(p) for p in (draft_product, published)}

    shop_client.post(
        UPDATE_URL,
        {"ids": [draft_product.id, published.id], "is_available": False},
        format="json",
    )

    for product in (draft_product, published):
        after = snapshot(product)
        old = before[product.id]
        assert after[:2] == old[:2]  # statut et published_at
        assert after[2] > old[2]  # updated_at
        assert after[5:] == old[5:]  # search_text_*
        assert after[4] is False


def test_bulk_update_identical_value_is_counted(shop_client):
    product = ProductFactory(shop=shop_client.shop, is_available=True)

    response = shop_client.post(
        UPDATE_URL, {"ids": [product.id], "is_available": True}, format="json"
    )

    assert response.json() == {"updated_count": 1}


# --- bulk-update : validation -------------------------------------------------------------
@pytest.mark.parametrize("extra", [{}, {"status": "DRAFT"}])
def test_bulk_update_without_any_field_returns_400(shop_client, extra):
    product = ProductFactory(shop=shop_client.shop)

    response = shop_client.post(UPDATE_URL, {"ids": [product.id], **extra}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "non_field_errors" in details(response)
    product.refresh_from_db()
    assert product.status == Product.Status.PUBLISHED


def test_bulk_update_other_shop_category_returns_400_and_changes_nothing(
    shop_client, other_shop_client
):
    own = CategoryFactory(shop=shop_client.shop)
    foreign = CategoryFactory(shop=other_shop_client.shop)
    product = ProductFactory(shop=shop_client.shop, category=own, is_available=True)

    response = shop_client.post(
        UPDATE_URL,
        {"ids": [product.id], "category_id": foreign.id, "is_available": False},
        format="json",
    )

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "category_id" in details(response)
    product.refresh_from_db()
    assert (product.category, product.is_available) == (own, True)


def test_bulk_update_unknown_category_same_error_as_other_shop(shop_client, other_shop_client):
    product = ProductFactory(shop=shop_client.shop)
    foreign = CategoryFactory(shop=other_shop_client.shop)

    unknown = shop_client.post(
        UPDATE_URL, {"ids": [product.id], "category_id": 999_999}, format="json"
    )
    other = shop_client.post(
        UPDATE_URL, {"ids": [product.id], "category_id": foreign.id}, format="json"
    )

    assert unknown.status_code == other.status_code == 400
    assert details(unknown) == details(other)


@pytest.mark.parametrize("value", ["abc", "oui", 2])
def test_bulk_update_invalid_is_available_returns_400(shop_client, value):
    product = ProductFactory(shop=shop_client.shop)

    response = shop_client.post(
        UPDATE_URL, {"ids": [product.id], "is_available": value}, format="json"
    )

    assert response.status_code == 400
    assert "is_available" in details(response)


# --- bulk-update : melange d'identifiants -----------------------------------------------------
def test_bulk_update_mixed_ids_updates_only_own_products(shop_client, other_shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    mine = [ProductFactory(shop=shop_client.shop, is_available=True) for _ in range(2)]
    foreign = ProductFactory(shop=other_shop_client.shop, is_available=True)
    foreign_before = snapshot(foreign)
    ids = [mine[0].id, foreign.id, 999_999, mine[1].id, mine[0].id]

    response = shop_client.post(
        UPDATE_URL,
        {"ids": ids, "category_id": category.id, "is_available": False},
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == {"updated_count": 2}
    assert snapshot(foreign) == foreign_before
    for product in mine:
        product.refresh_from_db()
        assert (product.category, product.is_available) == (category, False)


def test_bulk_update_only_foreign_and_unknown_ids_returns_zero(shop_client, other_shop_client):
    foreign = ProductFactory(shop=other_shop_client.shop, is_available=True)

    response = shop_client.post(
        UPDATE_URL, {"ids": [foreign.id, 999_999], "is_available": False}, format="json"
    )

    assert response.status_code == 200
    assert response.json() == {"updated_count": 0}
    foreign.refresh_from_db()
    assert foreign.is_available is True


# --- bulk-delete ------------------------------------------------------------------------------
def test_bulk_delete_removes_products_and_files(
    shop_client, real_product, django_capture_on_commit_callbacks
):
    products = [real_product(shop_client.shop) for _ in range(2)]
    kept = real_product(shop_client.shop)
    names = [name for p in products for name in (p.image.name, p.thumbnail.name)]

    with django_capture_on_commit_callbacks(execute=True):
        response = shop_client.post(DELETE_URL, {"ids": [p.id for p in products]}, format="json")

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 2}
    assert not Product.objects.filter(pk__in=[p.id for p in products]).exists()
    assert not any(default_storage.exists(name) for name in names)
    assert Product.objects.filter(pk=kept.id).exists()
    assert files_exist(kept)


def test_bulk_delete_mixed_ids_keeps_other_shop_product_and_files(
    shop_client, other_shop_client, real_product, django_capture_on_commit_callbacks
):
    mine = real_product(shop_client.shop)
    foreign = real_product(other_shop_client.shop)
    foreign_before = snapshot(foreign)
    ids = [foreign.id, mine.id, 999_999, mine.id]

    with django_capture_on_commit_callbacks(execute=True):
        response = shop_client.post(DELETE_URL, {"ids": ids}, format="json")

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1}
    assert not Product.objects.filter(pk=mine.id).exists()
    assert snapshot(foreign) == foreign_before
    assert files_exist(foreign)


def test_bulk_delete_only_foreign_and_unknown_ids_returns_zero(shop_client, other_shop_client):
    foreign = ProductFactory(shop=other_shop_client.shop)

    response = shop_client.post(DELETE_URL, {"ids": [foreign.id, 999_999]}, format="json")

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 0}
    assert Product.objects.filter(pk=foreign.id).exists()


def test_bulk_delete_keeps_order_items_and_counts_only_products(shop_client):
    product = ProductFactory(shop=shop_client.shop)
    order = OrderFactory(shop=shop_client.shop)
    items = [OrderItemFactory(order=order, product=product) for _ in range(2)]

    response = shop_client.post(DELETE_URL, {"ids": [product.id]}, format="json")

    assert response.json() == {"deleted_count": 1}
    for item in items:
        stored = OrderItem.objects.get(pk=item.pk)
        assert stored.product_id is None
        assert stored.product_name_fr == product.name_fr


# --- Validation de ids, roles et etats pour les trois endpoints ---------------------------------
BULK_ENDPOINTS = [
    (PUBLISH_URL, {}),
    (UPDATE_URL, {"is_available": False}),
    (DELETE_URL, {}),
]


@pytest.mark.parametrize("url, extra", BULK_ENDPOINTS)
@pytest.mark.parametrize(
    "ids",
    [None, [], "1,2", 5, [1, "abc"], [1.5], [0], [-4], [True], list(range(1, 1002))],
)
def test_bulk_invalid_ids_returns_400(shop_client, url, extra, ids):
    product = draft(shop_client.shop, is_available=True)
    payload = {**extra} if ids is None else {"ids": ids, **extra}

    response = shop_client.post(url, payload, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "ids" in details(response)
    assert Product.objects.filter(pk=product.id, status="DRAFT", is_available=True).exists()


@pytest.mark.parametrize("url, extra", BULK_ENDPOINTS)
def test_bulk_1000_ids_is_accepted(shop_client, url, extra):
    product = draft(shop_client.shop)

    response = shop_client.post(
        url, {"ids": [product.id, *range(10_000_000, 10_000_999)], **extra}, format="json"
    )

    assert response.status_code == 200


@pytest.mark.parametrize("url, extra", BULK_ENDPOINTS)
def test_bulk_without_authentication_returns_401(api_client, url, extra):
    product = draft(ProductFactory().shop)

    response = api_client.post(url, {"ids": [product.id], **extra}, format="json")

    assert response.status_code == 401
    assert error_code(response) == "AUTHENTICATION_REQUIRED"
    assert Product.objects.filter(pk=product.id, status="DRAFT", is_available=True).exists()


@pytest.mark.parametrize("url, extra", BULK_ENDPOINTS)
def test_bulk_as_admin_returns_403(admin_client, url, extra):
    product = draft(ProductFactory().shop)

    response = admin_client.post(url, {"ids": [product.id], **extra}, format="json")

    assert response.status_code == 403
    assert error_code(response) == "PERMISSION_DENIED"
    assert Product.objects.filter(pk=product.id, status="DRAFT", is_available=True).exists()


@pytest.mark.parametrize(
    "state, expected_code",
    [
        ("ONBOARDING", "SHOP_STATE_FORBIDDEN"),
        ("PENDING", "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", "SHOP_STATE_FORBIDDEN"),
        ("ACTIVE", None),
        ("EXPIRED", "SHOP_EXPIRED"),
        ("BLOCKED", "SHOP_BLOCKED"),
    ],
)
@pytest.mark.parametrize("url, extra", [(UPDATE_URL, {"is_available": False}), (DELETE_URL, {})])
def test_bulk_update_and_delete_by_shop_state(make_shop_client, state, expected_code, url, extra):
    client = make_shop_client(state=state)
    product = ProductFactory(shop=client.shop, is_available=True)

    response = client.post(url, {"ids": [product.id], **extra}, format="json")

    if expected_code is None:
        assert response.status_code == 200
        return
    assert response.status_code == 403
    assert error_code(response) == expected_code
    assert Product.objects.filter(pk=product.id, is_available=True).exists()


# --- Nombre de requetes -------------------------------------------------------------------------
@pytest.mark.parametrize("count", [1, 100])
def test_bulk_update_query_count_is_constant(shop_client, django_assert_max_num_queries, count):
    category = CategoryFactory(shop=shop_client.shop)
    ProductFactory.create_batch(count, shop=shop_client.shop)
    ids = list(Product.objects.filter(shop=shop_client.shop).values_list("id", flat=True))

    with django_assert_max_num_queries(UPDATE_MAX_QUERIES):
        response = shop_client.post(
            UPDATE_URL, {"ids": ids, "category_id": category.id}, format="json"
        )

    assert response.json() == {"updated_count": count}


@pytest.mark.parametrize("count, max_queries", [(1, 6), (100, 6), (1000, 15)])
def test_bulk_delete_query_count_is_bounded(
    shop_client, django_assert_max_num_queries, count, max_queries
):
    """Lecture des produits pour le signal + mise a NULL des lignes de commande + DELETE
    par lots de 100 (Django) : 5 requetes + une par lot de 100 produits."""
    Product.objects.bulk_create(
        Product(shop=shop_client.shop, name_fr=f"P{i}", price=1, image="p", thumbnail="t")
        for i in range(count)
    )
    ids = list(Product.objects.filter(shop=shop_client.shop).values_list("id", flat=True))

    with django_assert_max_num_queries(max_queries):
        response = shop_client.post(DELETE_URL, {"ids": ids}, format="json")

    assert response.json() == {"deleted_count": count}
