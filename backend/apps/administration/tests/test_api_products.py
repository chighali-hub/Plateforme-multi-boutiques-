"""Moderation des produits d'une boutique par l'administrateur."""

import pytest

from apps.accounts.tests.helpers import error_code
from apps.catalog.models import Product
from apps.catalog.tests.factories import CategoryFactory, ImportJobFactory, ProductFactory
from apps.core.models import AuditAction, AuditLog
from apps.notifications.models import Notification, NotificationType
from apps.orders.tests.factories import OrderItemFactory

pytestmark = pytest.mark.django_db
SHOPS = "/api/v1/admin/shops/"


def _products(shop):
    return f"{SHOPS}{shop.pk}/products/"


def _remove(shop, product):
    return f"{SHOPS}{shop.pk}/products/{product.pk}/remove/"


def _ids(response):
    return [item["id"] for item in response.json()["results"]]


@pytest.fixture
def catalog(make_shop):
    shop = make_shop("ACTIVE")
    category = CategoryFactory(shop=shop, name_fr="Melhfas", name_ar="ملاحف")
    job = ImportJobFactory(shop=shop)
    return {
        "shop": shop,
        "category": category,
        "melhfa": ProductFactory(shop=shop, name_fr="Melhfa bleue", category=category, price=2500),
        "parfum": ProductFactory(
            shop=shop, name_fr="Parfum Téléphone", name_ar="عطر", price=9000, is_available=False
        ),
        "draft": ProductFactory(
            shop=shop,
            name_fr="Voile",
            price=500,
            status=Product.Status.DRAFT,
            source=Product.Source.IMPORT,
            import_job=job,
        ),
        "job": job,
    }


def test_product_list_returns_product_objects(admin_client, catalog):
    response = admin_client.get(_products(catalog["shop"]))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    item = next(i for i in body["results"] if i["id"] == catalog["melhfa"].pk)
    assert set(item) == {
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
    assert item["category"] == {
        "id": catalog["category"].pk,
        "name_fr": "Melhfas",
        "name_ar": "ملاحف",
    }
    assert item["image_url"].startswith("http://testserver/media/")


def test_product_list_only_contains_the_shop_products(admin_client, catalog, make_shop):
    ProductFactory(shop=make_shop("ACTIVE"))

    assert admin_client.get(_products(catalog["shop"])).json()["count"] == 3


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"search": "MELHFA"}, ["melhfa"]),
        ({"search": "telephone"}, ["parfum"]),
        ({"search": "عطر"}, ["parfum"]),
        ({"status": "DRAFT"}, ["draft"]),
        ({"is_available": "false"}, ["parfum"]),
        ({"source": "IMPORT"}, ["draft"]),
        ({"uncategorized": "true", "ordering": "price"}, ["draft", "parfum"]),
        ({"min_price": 1000, "max_price": 5000}, ["melhfa"]),
        ({"min_price": 2500, "max_price": 2500}, ["melhfa"]),
        ({"ordering": "-price"}, ["parfum", "melhfa", "draft"]),
        ({"ordering": "name_fr"}, ["melhfa", "parfum", "draft"]),
    ],
)
def test_product_list_filters(admin_client, catalog, params, expected):
    response = admin_client.get(_products(catalog["shop"]), params)

    assert response.status_code == 200
    ids = _ids(response)
    if "ordering" in params:
        assert ids == [catalog[name].pk for name in expected]
    else:
        assert set(ids) == {catalog[name].pk for name in expected}


def test_product_list_filters_by_category_and_import_job(admin_client, catalog):
    by_category = admin_client.get(_products(catalog["shop"]), {"category": catalog["category"].pk})
    by_job = admin_client.get(_products(catalog["shop"]), {"import_job": catalog["job"].pk})

    assert _ids(by_category) == [catalog["melhfa"].pk]
    assert _ids(by_job) == [catalog["draft"].pk]


@pytest.mark.parametrize(
    "params",
    [
        {"min_price": 5000, "max_price": 1000},
        {"min_price": -1},
        {"category": "abc"},
        {"status": "ARCHIVED"},
        {"is_available": "oui"},
        {"ordering": "shop"},
        {"uncategorized": "false"},
    ],
)
def test_product_list_invalid_filters_return_400(admin_client, catalog, params):
    response = admin_client.get(_products(catalog["shop"]), params)
    assert response.status_code == 400 and error_code(response) == "VALIDATION_ERROR"


def test_product_list_of_unknown_shop_returns_404(admin_client):
    assert admin_client.get(f"{SHOPS}999999/products/").status_code == 404


def test_remove_product(admin_client, catalog):
    shop, product = catalog["shop"], catalog["melhfa"]
    item = OrderItemFactory(product=product, order__shop=shop)

    response = admin_client.post(_remove(shop, product), {"reason": "Produit contrefait."})

    assert response.status_code == 204
    assert not Product.objects.filter(pk=product.pk).exists()
    item.refresh_from_db()
    assert item.product is None and item.product_name_fr == "Melhfa bleue"
    notification = Notification.objects.get(recipient=shop.owner)
    assert notification.type == NotificationType.PRODUCT_REMOVED
    assert notification.data == {"product_name": "Melhfa bleue", "reason": "Produit contrefait."}
    entry = AuditLog.objects.get(action=AuditAction.PRODUCT_REMOVED_BY_ADMIN)
    assert (entry.target_type, entry.target_id) == ("product", product.pk)
    assert entry.metadata["price"] == 2500
    assert entry.metadata["product_name"] == "Melhfa bleue"
    assert entry.metadata["shop_id"] == shop.pk
    audit = admin_client.get(f"{SHOPS}{shop.pk}/").json()["recent_audit"]
    assert audit[0]["action"] == "PRODUCT_REMOVED_BY_ADMIN"


@pytest.mark.parametrize("reason", ["", "abc", "x" * 501])
def test_remove_product_reason_is_validated(admin_client, catalog, reason):
    response = admin_client.post(_remove(catalog["shop"], catalog["melhfa"]), {"reason": reason})

    assert response.status_code == 400
    assert Product.objects.filter(pk=catalog["melhfa"].pk).exists()


def test_remove_product_of_another_shop_returns_404(admin_client, catalog, make_shop):
    other = make_shop("ACTIVE")

    response = admin_client.post(_remove(other, catalog["melhfa"]), {"reason": "Contrefacon."})

    assert response.status_code == 404
    assert Product.objects.filter(pk=catalog["melhfa"].pk).exists()
    assert not Notification.objects.exists()
