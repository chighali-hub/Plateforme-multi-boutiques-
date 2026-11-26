"""Filtres de la liste des produits de l'espace boutique (GET /shop/products/).

Voir 03-reference-api.md section 6 et 05-aspects-transversaux.md section 5 :
toute valeur invalide renvoie 400 VALIDATION_ERROR, jamais un filtre ignore en
silence. Les regles reprennent celles de GET /admin/shops/{id}/products/
(apps/administration/serializers.py::ProductListQuerySerializer), qui applique
« les memes filtres ».
"""

import django_filters
from django import forms
from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from apps.core.text import normalize_search_text

from .models import Category, Product
from .services import PRODUCT_CATEGORY_UNKNOWN

SEARCH_MAX_LENGTH = 100
SEARCH_MAX_WORDS = 5
PRODUCT_ORDERINGS = ("created_at", "-created_at", "price", "-price", "name_fr", "-name_fr")
TRUE_FALSE = (("true", "true"), ("false", "false"))

PRICE_RANGE_INVALID = _("Le prix minimum doit être inférieur ou égal au prix maximum.")


def search_words(text: str) -> list[str]:
    """Mots de recherche : texte normalise, mots d'une lettre ignores, 5 au maximum.

    Meme normalisation que les colonnes `search_text_*` (05 section 9.2).
    """
    words = normalize_search_text(text or "").split()
    return [word for word in words if len(word) > 1][:SEARCH_MAX_WORDS]


@extend_schema_field(OpenApiTypes.INT)
class IntegerFilter(django_filters.NumberFilter):
    """Entier strict : `2.5` ou `abc` sont refuses (NumberFilter accepte les decimaux)."""

    field_class = forms.IntegerField


class ProductFilterForm(forms.Form):
    """Controles croises des parametres de la liste.

    Un parametre vide (`?status=`) est ignore, comme dans l'admin.
    """

    def clean(self):
        cleaned = super().clean()
        min_price, max_price = cleaned.get("min_price"), cleaned.get("max_price")
        if min_price is not None and max_price is not None and min_price > max_price:
            self.add_error("min_price", PRICE_RANGE_INVALID)
        return cleaned


def _shop_categories(request) -> QuerySet[Category]:
    """Seules les categories de la boutique connectee sont acceptees."""
    return Category.objects.filter(shop=request.shop)


class ProductFilterSet(django_filters.FilterSet):
    """Parametres de GET /shop/products/ ; ils se combinent (ET logique).

    Le queryset recu part deja de `request.shop` (selectors.get_shop_products).
    """

    search = django_filters.CharFilter(
        method="filter_search",
        max_length=SEARCH_MAX_LENGTH,
        label="Recherche dans les noms et descriptions (FR et AR), insensible à la casse et "
        "aux accents ; chaque mot doit être trouvé (100 caractères max).",
    )
    category = django_filters.ModelChoiceFilter(
        queryset=_shop_categories,
        error_messages={"invalid_choice": PRODUCT_CATEGORY_UNKNOWN},
        label="Identifiant d'une catégorie de la boutique.",
    )
    uncategorized = django_filters.ChoiceFilter(
        choices=(("true", "true"),),
        method="filter_uncategorized",
        label="`true` : produits sans catégorie.",
    )
    status = django_filters.ChoiceFilter(
        choices=Product.Status.choices, label="Statut : `DRAFT` ou `PUBLISHED`."
    )
    is_available = django_filters.ChoiceFilter(
        choices=TRUE_FALSE,
        method="filter_is_available",
        label="Disponibilité : `true` ou `false`.",
    )
    source = django_filters.ChoiceFilter(
        choices=Product.Source.choices, label="Origine : `MANUAL` ou `IMPORT`."
    )
    import_job = IntegerFilter(
        field_name="import_job_id",
        min_value=1,
        label="Identifiant d'un import : produits issus de cet import (liste 1 : "
        "`?status=DRAFT&import_job=12`).",
    )
    min_price = IntegerFilter(
        field_name="price", lookup_expr="gte", min_value=0, label="Prix minimum (inclus)."
    )
    max_price = IntegerFilter(
        field_name="price", lookup_expr="lte", min_value=0, label="Prix maximum (inclus)."
    )
    ordering = django_filters.ChoiceFilter(
        choices=[(value, value) for value in PRODUCT_ORDERINGS],
        method="filter_ordering",
        label="Tri : `created_at`, `-created_at` (défaut), `price`, `-price`, `name_fr`, "
        "`-name_fr`.",
    )

    class Meta:
        model = Product
        fields: list = []
        form = ProductFilterForm

    def filter_search(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        """Chaque mot doit etre contenu dans `search_text_fr` ou `search_text_ar`.

        LIKE sensible a la casse sur un texte deja normalise (minuscules, sans
        accents) : il utilise les index GIN trigrammes. Aucune tolerance aux fautes
        ici (recherche du site public, phase 7). Un texte vide apres normalisation
        n'applique aucun filtre.
        """
        for word in search_words(value):
            queryset = queryset.filter(
                Q(search_text_fr__contains=word) | Q(search_text_ar__contains=word)
            )
        return queryset

    def filter_uncategorized(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        return queryset.filter(category__isnull=True)

    def filter_is_available(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        return queryset.filter(is_available=value == "true")

    def filter_ordering(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        """Tri demande, puis `id` dans le meme sens (ordre stable entre les pages)."""
        return queryset.order_by(value, "-id" if value.startswith("-") else "id")
