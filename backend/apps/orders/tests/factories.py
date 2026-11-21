import factory

from apps.catalog.tests.factories import ProductFactory
from apps.orders.models import Order, OrderItem
from apps.shops.tests.factories import ShopFactory


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    reference = factory.Sequence(lambda n: f"CMD-2026-{n:06d}")
    shop = factory.SubFactory(ShopFactory, active=True)
    customer_name = "Client Test"
    customer_phone = "46123456"
    total_amount = 6000
    deposit_percent = 30
    deposit_required = 1800
    amount_paid = 1800
    payment_proof = "payment_proofs/2026/01/capture.jpg"


class OrderItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    product = factory.SubFactory(ProductFactory, shop=factory.SelfAttribute("..order.shop"))
    product_name_fr = factory.SelfAttribute("product.name_fr")
    product_name_ar = factory.SelfAttribute("product.name_ar")
    unit_price = 3000
    quantity = 2
    line_total = factory.LazyAttribute(lambda item: item.unit_price * item.quantity)
