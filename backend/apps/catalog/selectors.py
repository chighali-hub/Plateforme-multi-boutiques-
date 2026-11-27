"""Lectures du catalogue de l'espace boutique.

Voir 03-reference-api.md section 6 et 05-aspects-transversaux.md sections 4.3 et 6.
Toute lecture part de la boutique connectee : jamais de queryset global.
"""

from django.db.models import Count, QuerySet

from apps.shops.models import Shop

from .models import Category, Product


def get_shop_categories(shop: Shop) -> QuerySet[Category]:
    """Categories de la boutique, avec `products_count`, dans l'ordre d'affichage.

    Tri : `sort_order`, puis `name_fr`, puis `id` (ordre stable). Le compteur est
    calcule par une seule requete (`annotate`), brouillons compris.
    """
    return (
        Category.objects.filter(shop=shop)
        .annotate(products_count=Count("products"))
        .order_by("sort_order", "name_fr", "id")
    )


def get_shop_products(shop: Shop) -> QuerySet[Product]:
    """Produits de la boutique (brouillons compris), du plus recent au plus ancien.

    La categorie est chargee dans la meme requete (`select_related`) : le nombre
    de requetes d'une page ne depend pas du nombre de produits.
    """
    return (
        Product.objects.filter(shop=shop).select_related("category").order_by("-created_at", "-id")
    )
