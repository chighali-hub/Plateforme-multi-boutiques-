"""Calcul du panier et de l'acompte (RG-43, RG-44).

Partage par le devis (phase 7) et la soumission de commande (phase 8). Les prix
viennent toujours de la base, jamais du client.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from apps.catalog.models import Product
from apps.shops.models import Shop


def compute_deposit(total: int, percent: int) -> int:
    """Acompte minimum = arrondi superieur de total x percent / 100.

    Arithmetique entiere, sans flottant : (1001 x 30 + 99) // 100 = 301.
    """
    if total < 0:
        raise ValueError("Le total ne peut pas etre negatif.")
    if not 1 <= percent <= 100:
        raise ValueError("Le pourcentage d'acompte doit etre compris entre 1 et 100.")
    return (total * percent + 99) // 100


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int
    unit_price: int
    line_total: int


@dataclass(frozen=True)
class CartResult:
    lines: list[CartLine] = field(default_factory=list)
    unavailable_product_ids: list[int] = field(default_factory=list)
    total_amount: int = 0


def compute_cart(shop: Shop, items: Iterable[Mapping[str, int]]) -> CartResult:
    """Recalcule un panier pour une boutique.

    `items` : [{"product_id": int, "quantity": int}, ...], deja valide par le
    serializer (1 a 50 lignes, quantite 1 a 99, identifiants distincts).
    Un produit absent, d'une autre boutique, en brouillon ou indisponible est
    exclu du total et renvoye dans `unavailable_product_ids`, dans l'ordre du panier.
    """
    requested = [(int(item["product_id"]), int(item["quantity"])) for item in items]
    product_ids = [product_id for product_id, _quantity in requested]
    available = {
        product.pk: product
        for product in Product.objects.filter(
            shop=shop,
            pk__in=product_ids,
            status=Product.Status.PUBLISHED,
            is_available=True,
        )
    }

    lines: list[CartLine] = []
    unavailable: list[int] = []
    for product_id, quantity in requested:
        product = available.get(product_id)
        if product is None:
            unavailable.append(product_id)
            continue
        lines.append(
            CartLine(
                product=product,
                quantity=quantity,
                unit_price=product.price,
                line_total=product.price * quantity,
            )
        )
    return CartResult(
        lines=lines,
        unavailable_product_ids=unavailable,
        total_amount=sum(line.line_total for line in lines),
    )
