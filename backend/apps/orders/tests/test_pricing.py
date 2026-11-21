import pytest

from apps.catalog.models import Product
from apps.catalog.tests.factories import ProductFactory
from apps.orders.pricing import compute_cart, compute_deposit


@pytest.mark.parametrize(
    "total, percent, expected",
    [
        (6000, 30, 1800),
        (1001, 30, 301),  # arrondi superieur : 300,3 -> 301
        (1, 30, 1),
        (6000, 100, 6000),
        (999, 1, 10),  # 9,99 -> 10
        (0, 30, 0),
        (100_000_000 * 99 * 50, 30, 148_500_000_000),  # aucun flottant, aucune perte
    ],
)
def test_compute_deposit(total, percent, expected):
    assert compute_deposit(total, percent) == expected


@pytest.mark.parametrize("total, percent", [(-1, 30), (100, 0), (100, 101)])
def test_compute_deposit_rejects_invalid_inputs(total, percent):
    with pytest.raises(ValueError):
        compute_deposit(total, percent)


@pytest.mark.django_db
def test_compute_cart_uses_database_prices(make_shop):
    shop = make_shop("ACTIVE")
    first = ProductFactory(shop=shop, price=2500)
    second = ProductFactory(shop=shop, price=1000)

    result = compute_cart(
        shop,
        [
            {"product_id": first.id, "quantity": 2, "unit_price": 1},
            {"product_id": second.id, "quantity": 1},
        ],
    )

    assert [(line.product.id, line.unit_price, line.line_total) for line in result.lines] == [
        (first.id, 2500, 5000),
        (second.id, 1000, 1000),
    ]
    assert result.total_amount == 6000
    assert result.unavailable_product_ids == []


@pytest.mark.django_db
def test_compute_cart_excludes_unavailable_and_foreign_products(make_shop):
    shop = make_shop("ACTIVE")
    ok = ProductFactory(shop=shop, price=1000)
    draft = ProductFactory(shop=shop, status=Product.Status.DRAFT)
    hidden = ProductFactory(shop=shop, is_available=False)
    foreign = ProductFactory(price=5)
    deleted_id = ProductFactory(shop=shop).id
    Product.objects.filter(pk=deleted_id).delete()

    items = [
        {"product_id": product_id, "quantity": 1}
        for product_id in (draft.id, ok.id, hidden.id, foreign.id, deleted_id)
    ]
    result = compute_cart(shop, items)

    assert [line.product.id for line in result.lines] == [ok.id]
    assert result.unavailable_product_ids == [draft.id, hidden.id, foreign.id, deleted_id]
    assert result.total_amount == 1000


@pytest.mark.django_db
def test_compute_cart_runs_one_query(make_shop, django_assert_num_queries):
    shop = make_shop("ACTIVE")
    items = [{"product_id": ProductFactory(shop=shop).id, "quantity": 1} for _ in range(30)]
    with django_assert_num_queries(1):
        compute_cart(shop, items)


@pytest.mark.django_db
def test_compute_cart_empty(make_shop):
    result = compute_cart(make_shop("ACTIVE"), [])
    assert (result.lines, result.unavailable_product_ids, result.total_amount) == ([], [], 0)
