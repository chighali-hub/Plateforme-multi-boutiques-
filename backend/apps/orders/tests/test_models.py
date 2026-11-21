import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.core.storage import PrivateMediaStorage
from apps.orders.models import Order
from apps.orders.tests.factories import OrderFactory, OrderItemFactory

pytestmark = pytest.mark.django_db


def test_rejected_order_requires_reason():
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderFactory(status=Order.Status.REJECTED, rejection_reason="")


def test_rejected_order_with_reason_is_accepted():
    assert OrderFactory(status=Order.Status.REJECTED, rejection_reason="Capture illisible.").pk


def test_delivered_order_requires_delivery_date():
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderFactory(status=Order.Status.DELIVERED, delivered_at=None)
    assert OrderFactory(status=Order.Status.DELIVERED, delivered_at=timezone.now()).pk


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "LOST"},
        {"total_amount": 0},
        {"deposit_percent": 0},
        {"customer_phone": "12345678"},
    ],
)
def test_order_constraints(fields):
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderFactory(**fields)


def test_reference_is_unique():
    OrderFactory(reference="CMD-2026-000001")
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderFactory(reference="CMD-2026-000001")


@pytest.mark.parametrize("quantity", [0, 100])
def test_item_quantity_range(quantity):
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItemFactory(quantity=quantity)


def test_item_line_total_must_equal_price_times_quantity():
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItemFactory(unit_price=1000, quantity=3, line_total=2000)


@pytest.mark.parametrize("paid, expected", [(1800, 4200), (6000, 0), (7000, 0)])
def test_remaining_amount_never_negative(paid, expected):
    assert OrderFactory(total_amount=6000, amount_paid=paid).remaining_amount == expected


def test_order_keeps_product_copy_when_product_deleted():
    item = OrderItemFactory(
        product_name_fr="Melhfa bleue", unit_price=2500, quantity=1, line_total=2500
    )
    item.product.delete()
    item.refresh_from_db()
    assert item.product is None
    assert (item.product_name_fr, item.unit_price) == ("Melhfa bleue", 2500)


def test_shop_with_orders_cannot_be_deleted():
    order = OrderFactory()
    with pytest.raises(ProtectedError):
        order.shop.delete()


def test_payment_proof_uses_private_storage():
    assert isinstance(Order._meta.get_field("payment_proof").storage, PrivateMediaStorage)
