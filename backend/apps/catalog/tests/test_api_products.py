"""Endpoints des produits de l'espace boutique : CRUD unitaire (03-reference-api.md section 6)."""

import io

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.catalog import services
from apps.catalog.models import Product, product_search_texts
from apps.catalog.tests.factories import CategoryFactory, ImportJobFactory, ProductFactory
from apps.orders.models import OrderItem
from apps.orders.tests.factories import OrderFactory, OrderItemFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/shop/products/"
LIST_MAX_QUERIES = 3


def detail_url(product_id: int) -> str:
    return f"/api/v1/shop/products/{product_id}/"


def error_code(response) -> str:
    return response.json()["error"]["code"]


def details(response) -> dict:
    return response.json()["error"]["details"]


@pytest.fixture
def make_product(image_file):
    """Produit avec de vrais fichiers image, cree par le service."""

    def _make(shop, **data):
        payload = {"name_fr": "Melhfa bleue", "price": 2500, **data}
        return services.create_product_from_data(shop, payload, image_file())

    return _make


def post_product(client, image_file, **data):
    payload = {"name_fr": "Melhfa bleue", "price": "2500", "image": image_file(), **data}
    return client.post(LIST_URL, payload, format="multipart")


def files_exist(product: Product) -> bool:
    return default_storage.exists(product.image.name) and default_storage.exists(
        product.thumbnail.name
    )


# --- Creation -----------------------------------------------------------------------
def test_create_published_product_returns_201_with_reference_fields(shop_client, image_file):
    category = CategoryFactory(shop=shop_client.shop, name_fr="Melhfas", name_ar="ملاحف")

    response = post_product(
        shop_client,
        image_file,
        name_ar="ملحفة زرقاء",
        description_fr="Voile léger 100 % coton.",
        category_id=category.id,
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "name_fr",
        "name_ar",
        "description_fr",
        "description_ar",
        "price",
        "category",
        "image_url",
        "thumbnail_url",
        "status",
        "is_available",
        "source",
        "import_job_id",
        "published_at",
        "created_at",
        "updated_at",
    }
    assert body["price"] == 2500
    assert body["category"] == {"id": category.id, "name_fr": "Melhfas", "name_ar": "ملاحف"}
    assert body["status"] == "PUBLISHED"
    assert body["is_available"] is True
    assert body["source"] == "MANUAL"
    assert body["import_job_id"] is None
    assert body["published_at"] is not None
    assert body["image_url"].startswith("http://testserver/media/products/")
    assert body["thumbnail_url"].startswith("http://testserver/media/products/")
    product = Product.objects.get(pk=body["id"])
    assert product.shop == shop_client.shop
    assert product.category == category
    assert files_exist(product)


def test_create_draft_product_leaves_published_at_null(shop_client, image_file):
    response = post_product(shop_client, image_file, status="DRAFT", is_available="false")

    assert response.status_code == 201
    assert response.json()["published_at"] is None
    product = Product.objects.get(pk=response.json()["id"])
    assert (product.status, product.is_available, product.published_at) == ("DRAFT", False, None)


def test_create_product_stores_webp_image_and_thumbnail(shop_client, image_file):
    response = post_product(shop_client, image_file, image=image_file("PNG", size=(2400, 1200)))

    assert response.status_code == 201
    product = Product.objects.get(pk=response.json()["id"])
    assert product.image.name.startswith("products/") and product.image.name.endswith(".webp")
    assert product.thumbnail.name.endswith(".webp")
    assert product.image.name != product.thumbnail.name
    with default_storage.open(product.image.name) as handle, Image.open(handle) as image:
        assert (image.format, max(image.size)) == ("WEBP", 1600)
    with default_storage.open(product.thumbnail.name) as handle, Image.open(handle) as thumb:
        assert (thumb.format, max(thumb.size)) == ("WEBP", 400)


def test_create_product_removes_exif_metadata(shop_client):
    exif = Image.Exif()
    exif[0x010F] = "Fabricant secret"
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (10, 120, 60)).save(buffer, format="JPEG", exif=exif)
    upload = SimpleUploadedFile("photo.jpg", buffer.getvalue(), content_type="image/jpeg")

    response = shop_client.post(
        LIST_URL, {"name_fr": "Melhfa", "price": "2500", "image": upload}, format="multipart"
    )

    assert response.status_code == 201
    product = Product.objects.get(pk=response.json()["id"])
    for field_file in (product.image, product.thumbnail):
        with default_storage.open(field_file.name) as handle, Image.open(handle) as image:
            assert "exif" not in image.info
            assert len(image.getexif()) == 0


def test_create_product_strips_texts(shop_client, image_file):
    response = post_product(
        shop_client, image_file, name_fr="  Melhfa  ", description_fr="  Coton  "
    )

    assert response.status_code == 201
    product = Product.objects.get(pk=response.json()["id"])
    assert (product.name_fr, product.description_fr) == ("Melhfa", "Coton")


def test_create_product_computes_search_texts(shop_client, image_file):
    response = post_product(
        shop_client, image_file, name_fr="Téléphone", name_ar="هاتف", description_ar="جَديد"
    )

    product = Product.objects.get(pk=response.json()["id"])
    expected = product_search_texts("Téléphone", "هاتف", "", "جَديد")
    assert (product.search_text_fr, product.search_text_ar) == expected
    assert product.search_text_fr == "telefone"


def test_create_product_ignores_protected_fields(shop_client, other_shop_client, image_file):
    job = ImportJobFactory(shop=shop_client.shop)

    response = post_product(
        shop_client,
        image_file,
        status="DRAFT",
        shop=other_shop_client.shop.id,
        source="IMPORT",
        import_job=job.id,
        import_job_id=job.id,
        published_at="2020-01-01T00:00:00+00:00",
        search_text_fr="pirate",
        thumbnail="products/2020/01/x.webp",
    )

    assert response.status_code == 201
    product = Product.objects.get(pk=response.json()["id"])
    assert product.shop == shop_client.shop
    assert (product.source, product.import_job, product.published_at) == ("MANUAL", None, None)
    assert "pirate" not in product.search_text_fr
    assert not Product.objects.filter(shop=other_shop_client.shop).exists()


def test_create_product_without_image_returns_400(shop_client):
    response = shop_client.post(
        LIST_URL, {"name_fr": "Melhfa", "price": "2500"}, format="multipart"
    )

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "image" in details(response)
    assert not Product.objects.exists()


def test_create_product_with_fake_image_returns_400(shop_client, image_file, fake_image_file):
    response = post_product(shop_client, image_file, image=fake_image_file)

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "image" in details(response)
    assert not Product.objects.exists()


def test_create_product_with_image_over_5_mb_returns_413(shop_client, image_file):
    too_big = SimpleUploadedFile(
        "photo.jpg", b"\0" * (5 * 1024 * 1024 + 1), content_type="image/jpeg"
    )

    response = post_product(shop_client, image_file, image=too_big)

    assert response.status_code == 413
    assert error_code(response) == "FILE_TOO_LARGE"
    assert details(response)["field"] == "image"
    assert not Product.objects.exists()


def test_create_product_without_price_returns_400(shop_client, image_file):
    response = shop_client.post(
        LIST_URL, {"name_fr": "Melhfa", "image": image_file()}, format="multipart"
    )

    assert response.status_code == 400
    assert "price" in details(response)


@pytest.mark.parametrize("price", ["0", "-5", "100000001", "2500.5", "abc", "true", ""])
def test_create_product_with_invalid_price_returns_400(shop_client, image_file, price):
    response = post_product(shop_client, image_file, price=price)

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "price" in details(response)
    assert not Product.objects.exists()


@pytest.mark.parametrize("price", [1, 100_000_000])
def test_create_product_with_price_bounds_is_accepted(shop_client, image_file, price):
    response = post_product(shop_client, image_file, price=str(price))

    assert response.status_code == 201
    assert Product.objects.get(pk=response.json()["id"]).price == price


@pytest.mark.parametrize("payload", [{"name_fr": ""}, {"name_fr": "  ", "name_ar": " "}])
def test_create_product_without_any_name_returns_400(shop_client, image_file, payload):
    response = post_product(shop_client, image_file, **payload)

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "non_field_errors" in details(response)
    assert not Product.objects.exists()


@pytest.mark.parametrize("field", ["name_fr", "name_ar"])
def test_create_product_name_length_limit(shop_client, image_file, field):
    accepted = post_product(shop_client, image_file, **{field: "a" * 150})
    refused = post_product(shop_client, image_file, **{field: "b" * 151})

    assert accepted.status_code == 201
    assert refused.status_code == 400
    assert field in details(refused)
    assert Product.objects.count() == 1


@pytest.mark.parametrize("field", ["description_fr", "description_ar"])
def test_create_product_description_length_limit(shop_client, image_file, field):
    accepted = post_product(shop_client, image_file, **{field: "a" * 2000})
    refused = post_product(shop_client, image_file, **{field: "b" * 2001})

    assert accepted.status_code == 201
    assert refused.status_code == 400
    assert field in details(refused)
    assert Product.objects.count() == 1


def test_create_product_with_other_shop_category_returns_400(
    shop_client, other_shop_client, image_file
):
    foreign = CategoryFactory(shop=other_shop_client.shop)

    response = post_product(shop_client, image_file, category_id=foreign.id)

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "category_id" in details(response)
    assert not Product.objects.exists()


def test_create_product_with_unknown_category_returns_same_error(
    shop_client, other_shop_client, image_file
):
    foreign = CategoryFactory(shop=other_shop_client.shop)

    unknown = post_product(shop_client, image_file, category_id=999_999)
    other = post_product(shop_client, image_file, category_id=foreign.id)

    assert unknown.status_code == other.status_code == 400
    assert details(unknown) == details(other)


@pytest.mark.parametrize("status_value", ["ARCHIVED", "published"])
def test_create_product_with_invalid_status_returns_400(shop_client, image_file, status_value):
    response = post_product(shop_client, image_file, status=status_value)

    assert response.status_code == 400
    assert "status" in details(response)


# --- Limite de 5 000 produits ---------------------------------------------------------
def _bulk_products(shop, count: int) -> None:
    Product.objects.bulk_create(
        Product(shop=shop, name_fr=f"P{i}", price=1, image="p.webp", thumbnail="t.webp")
        for i in range(count)
    )


def test_create_5000th_product_is_accepted(shop_client, image_file):
    _bulk_products(shop_client.shop, services.MAX_PRODUCTS - 1)

    response = post_product(shop_client, image_file, status="DRAFT")

    assert response.status_code == 201
    assert Product.objects.filter(shop=shop_client.shop).count() == services.MAX_PRODUCTS


def test_create_5001st_product_returns_409_limit_reached(shop_client, image_file):
    _bulk_products(shop_client.shop, services.MAX_PRODUCTS)

    response = post_product(shop_client, image_file)

    assert response.status_code == 409
    assert error_code(response) == "LIMIT_REACHED"
    assert details(response) == {"limit": 5000}
    assert Product.objects.filter(shop=shop_client.shop).count() == services.MAX_PRODUCTS
    assert not default_storage.exists("products")


# --- Liste minimale -------------------------------------------------------------------
def test_list_products_is_paginated_and_sorted_newest_first(shop_client):
    products = ProductFactory.create_batch(3, shop=shop_client.shop)

    response = shop_client.get(LIST_URL)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 3
    assert [item["id"] for item in body["results"]] == [p.id for p in reversed(products)]


def test_list_products_includes_drafts(shop_client):
    ProductFactory(shop=shop_client.shop, status=Product.Status.DRAFT)

    response = shop_client.get(LIST_URL)

    assert response.json()["count"] == 1


def test_list_products_page_size_is_20_by_default(shop_client):
    ProductFactory.create_batch(21, shop=shop_client.shop)

    response = shop_client.get(LIST_URL)

    assert len(response.json()["results"]) == 20
    assert response.json()["next"] is not None


def test_list_products_out_of_range_page_returns_404(shop_client):
    response = shop_client.get(LIST_URL, {"page": 5})

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_list_products_never_shows_other_shop_products(shop_client, other_shop_client):
    mine = ProductFactory(shop=shop_client.shop)
    ProductFactory(shop=other_shop_client.shop)

    response = shop_client.get(LIST_URL)

    assert [item["id"] for item in response.json()["results"]] == [mine.id]


@pytest.mark.parametrize("count", [1, 30])
def test_list_products_query_count_is_constant(shop_client, django_assert_max_num_queries, count):
    category = CategoryFactory(shop=shop_client.shop)
    ProductFactory.create_batch(count, shop=shop_client.shop, category=category)

    with django_assert_max_num_queries(LIST_MAX_QUERIES):
        response = shop_client.get(LIST_URL, {"page_size": 50})

    assert response.status_code == 200
    assert len(response.json()["results"]) == count


# --- Detail -----------------------------------------------------------------------------
def test_get_product_returns_200(shop_client):
    product = ProductFactory(shop=shop_client.shop, category=None)

    response = shop_client.get(detail_url(product.id))

    assert response.status_code == 200
    assert response.json()["id"] == product.id
    assert response.json()["category"] is None


def test_get_unknown_product_returns_404(shop_client):
    response = shop_client.get(detail_url(999_999))

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


# --- Modification ---------------------------------------------------------------------
def test_patch_product_with_json_returns_200(shop_client):
    product = ProductFactory(shop=shop_client.shop, price=2500, is_available=True)

    response = shop_client.patch(
        detail_url(product.id), {"price": 3000, "is_available": False}, format="json"
    )

    assert response.status_code == 200
    assert (response.json()["price"], response.json()["is_available"]) == (3000, False)
    product.refresh_from_db()
    assert (product.price, product.is_available) == (3000, False)


def test_patch_product_with_new_image_replaces_and_deletes_old_files(
    shop_client, make_product, image_file, django_capture_on_commit_callbacks
):
    product = make_product(shop_client.shop)
    old_image, old_thumbnail = product.image.name, product.thumbnail.name

    with django_capture_on_commit_callbacks(execute=True):
        response = shop_client.patch(
            detail_url(product.id), {"image": image_file("WEBP")}, format="multipart"
        )

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.image.name != old_image
    assert files_exist(product)
    assert not default_storage.exists(old_image)
    assert not default_storage.exists(old_thumbnail)


def test_patch_product_without_image_keeps_files(
    shop_client, make_product, django_capture_on_commit_callbacks
):
    product = make_product(shop_client.shop)
    old_image = product.image.name

    with django_capture_on_commit_callbacks(execute=True):
        response = shop_client.patch(detail_url(product.id), {"name_fr": "Autre"}, format="json")

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.image.name == old_image
    assert files_exist(product)


def test_patch_product_draft_to_published_sets_published_at(shop_client):
    product = ProductFactory(shop=shop_client.shop, status=Product.Status.DRAFT, published_at=None)

    response = shop_client.patch(detail_url(product.id), {"status": "PUBLISHED"}, format="json")

    assert response.status_code == 200
    assert response.json()["published_at"] is not None
    product.refresh_from_db()
    assert product.published_at is not None


def test_patch_published_product_staying_published_keeps_published_at(shop_client, image_file):
    created = post_product(shop_client, image_file)
    product = Product.objects.get(pk=created.json()["id"])
    published_at = product.published_at

    response = shop_client.patch(
        detail_url(product.id), {"status": "PUBLISHED", "price": 10}, format="json"
    )

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.published_at == published_at


def test_patch_published_product_to_draft_keeps_published_at(shop_client, image_file):
    created = post_product(shop_client, image_file)
    product = Product.objects.get(pk=created.json()["id"])
    published_at = product.published_at

    response = shop_client.patch(detail_url(product.id), {"status": "DRAFT"}, format="json")

    assert response.status_code == 200
    product.refresh_from_db()
    assert (product.status, product.published_at) == ("DRAFT", published_at)


def test_patch_product_emptying_only_name_returns_400(shop_client):
    product = ProductFactory(shop=shop_client.shop, name_fr="Melhfa", name_ar="")

    response = shop_client.patch(detail_url(product.id), {"name_fr": " "}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "non_field_errors" in details(response)
    product.refresh_from_db()
    assert product.name_fr == "Melhfa"


def test_patch_product_updates_search_texts(shop_client):
    product = ProductFactory(shop=shop_client.shop, name_fr="Melhfa", name_ar="")

    response = shop_client.patch(
        detail_url(product.id), {"name_fr": "Téléphone", "description_fr": "Neuf"}, format="json"
    )

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.search_text_fr == "telefone neuf"


def test_patch_product_with_own_category_sets_it(shop_client):
    product = ProductFactory(shop=shop_client.shop, category=None)
    category = CategoryFactory(shop=shop_client.shop)

    response = shop_client.patch(
        detail_url(product.id), {"category_id": category.id}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["category"]["id"] == category.id
    product.refresh_from_db()
    assert product.category == category


def test_patch_product_with_null_category_removes_it(shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    product = ProductFactory(shop=shop_client.shop, category=category)

    response = shop_client.patch(detail_url(product.id), {"category_id": None}, format="json")

    assert response.status_code == 200
    assert response.json()["category"] is None
    product.refresh_from_db()
    assert product.category is None


def test_patch_product_with_other_shop_category_returns_400(shop_client, other_shop_client):
    category = CategoryFactory(shop=shop_client.shop)
    product = ProductFactory(shop=shop_client.shop, category=category)
    foreign = CategoryFactory(shop=other_shop_client.shop)

    response = shop_client.patch(detail_url(product.id), {"category_id": foreign.id}, format="json")

    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"
    assert "category_id" in details(response)
    product.refresh_from_db()
    assert product.category == category


@pytest.mark.parametrize("price", [0, 100_000_001, 2500.5, "abc", True])
def test_patch_product_with_invalid_price_returns_400(shop_client, price):
    product = ProductFactory(shop=shop_client.shop, price=2500)

    response = shop_client.patch(detail_url(product.id), {"price": price}, format="json")

    assert response.status_code == 400
    assert "price" in details(response)
    product.refresh_from_db()
    assert product.price == 2500


def test_patch_product_ignores_protected_fields(shop_client, other_shop_client):
    product = ProductFactory(shop=shop_client.shop, status=Product.Status.DRAFT, published_at=None)
    job = ImportJobFactory(shop=shop_client.shop)

    response = shop_client.patch(
        detail_url(product.id),
        {
            "shop": other_shop_client.shop.id,
            "source": "IMPORT",
            "import_job": job.id,
            "published_at": "2020-01-01T00:00:00+00:00",
        },
        format="json",
    )

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.shop == shop_client.shop
    assert (product.source, product.import_job, product.published_at) == ("MANUAL", None, None)


def test_patch_product_with_fake_image_returns_400_and_keeps_files(
    shop_client, make_product, fake_image_file
):
    product = make_product(shop_client.shop)
    old_image = product.image.name

    response = shop_client.patch(
        detail_url(product.id), {"image": fake_image_file}, format="multipart"
    )

    assert response.status_code == 400
    assert "image" in details(response)
    product.refresh_from_db()
    assert product.image.name == old_image
    assert files_exist(product)


# --- Suppression ----------------------------------------------------------------------
def test_delete_product_returns_204_and_deletes_files(
    shop_client, make_product, django_capture_on_commit_callbacks
):
    product = make_product(shop_client.shop)
    image, thumbnail = product.image.name, product.thumbnail.name

    with django_capture_on_commit_callbacks(execute=True):
        response = shop_client.delete(detail_url(product.id))

    assert response.status_code == 204
    assert not Product.objects.filter(pk=product.id).exists()
    assert not default_storage.exists(image)
    assert not default_storage.exists(thumbnail)


def test_delete_product_in_order_keeps_order_item(shop_client):
    product = ProductFactory(shop=shop_client.shop)
    item = OrderItemFactory(order=OrderFactory(shop=shop_client.shop), product=product)

    response = shop_client.delete(detail_url(product.id))

    assert response.status_code == 204
    item = OrderItem.objects.get(pk=item.pk)
    assert item.product_id is None
    assert item.product_name_fr == product.name_fr


# --- Authentification, role et isolation ------------------------------------------------
ENDPOINTS = [
    ("get", False, 200),
    ("post", False, 201),
    ("get", True, 200),
    ("patch", True, 200),
    ("delete", True, 204),
]


def _call(client, method: str, product, image_file):
    if product is None and method == "post":
        return post_product(client, image_file)
    url = detail_url(product.id) if product else LIST_URL
    if method == "patch":
        return client.patch(url, {"name_fr": "Modifié"}, format="json")
    return getattr(client, method)(url)


@pytest.mark.parametrize("method, with_product, _status", ENDPOINTS)
def test_products_without_authentication_returns_401(
    api_client, image_file, method, with_product, _status
):
    product = ProductFactory() if with_product else None

    response = _call(api_client, method, product, image_file)

    assert response.status_code == 401
    assert error_code(response) == "AUTHENTICATION_REQUIRED"
    if product:
        assert Product.objects.filter(pk=product.id, name_fr=product.name_fr).exists()


@pytest.mark.parametrize("method, with_product, _status", ENDPOINTS)
def test_products_as_admin_returns_403(admin_client, image_file, method, with_product, _status):
    product = ProductFactory() if with_product else None

    response = _call(admin_client, method, product, image_file)

    assert response.status_code == 403
    assert error_code(response) == "PERMISSION_DENIED"
    assert Product.objects.count() == (1 if product else 0)


STATE_CASES = [
    ("ONBOARDING", "SHOP_STATE_FORBIDDEN"),
    ("PENDING", "SHOP_STATE_FORBIDDEN"),
    ("REJECTED", "SHOP_STATE_FORBIDDEN"),
    ("ACTIVE", None),
    ("EXPIRED", "SHOP_EXPIRED"),
    ("BLOCKED", "SHOP_BLOCKED"),
]


@pytest.mark.parametrize("state, expected_code", STATE_CASES)
@pytest.mark.parametrize("method, with_product, success_status", ENDPOINTS)
def test_products_by_shop_state(
    make_shop_client, image_file, state, expected_code, method, with_product, success_status
):
    client = make_shop_client(state=state)
    product = ProductFactory(shop=client.shop, name_fr="Melhfa") if with_product else None

    response = _call(client, method, product, image_file)

    if expected_code is None:
        assert response.status_code == success_status
        return
    assert response.status_code == 403
    assert error_code(response) == expected_code
    assert Product.objects.filter(shop=client.shop).count() == (1 if product else 0)
    if product:
        assert Product.objects.filter(pk=product.id, name_fr="Melhfa").exists()


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_shop_cannot_access_other_shop_product_returns_404(
    shop_client,
    other_shop_client,
    make_product,
    image_file,
    method,
    django_capture_on_commit_callbacks,
):
    product = make_product(other_shop_client.shop, price=2500)

    with django_capture_on_commit_callbacks(execute=True):
        if method == "patch":
            response = shop_client.patch(
                detail_url(product.id), {"price": 1, "image": image_file()}, format="multipart"
            )
        else:
            response = getattr(shop_client, method)(detail_url(product.id))

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"
    stored = Product.objects.get(pk=product.id)
    assert (stored.price, stored.image.name) == (2500, product.image.name)
    assert files_exist(stored)
