"""Ecritures du catalogue de l'espace boutique : categories.

Voir 03-reference-api.md section 6, 04-schema-base-de-donnees.md section 5.1
et 01-vue-d-ensemble.md (RG-32). Les services appliquent les regles ; les vues
ne font qu'appeler.
"""

import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Value
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.core.exceptions import LimitReached
from apps.shops.models import Shop

from .models import Category

logger = logging.getLogger(__name__)

MAX_CATEGORIES = 100
CATEGORY_NAME_FIELDS = ("name_fr", "name_ar")
CATEGORY_FIELDS = frozenset({*CATEGORY_NAME_FIELDS, "sort_order"})
UNIQUE_CONSTRAINT_FIELDS = {
    "catalog_category_unique_name_fr": "name_fr",
    "catalog_category_unique_name_ar": "name_ar",
}

CATEGORY_NAME_REQUIRED = _("Renseignez au moins un nom, en français ou en arabe.")
CATEGORY_NAME_DUPLICATE = _("Une catégorie porte déjà ce nom dans votre boutique.")


def _apply_fields(category: Category, data: dict[str, Any]) -> None:
    """Recopie les champs autorises ; les noms sont debarrasses des espaces."""
    for name, value in data.items():
        if name not in CATEGORY_FIELDS:
            continue
        if name in CATEGORY_NAME_FIELDS:
            value = (value or "").strip()
        setattr(category, name, value)


def _ensure_has_name(category: Category) -> None:
    """Au moins un des deux noms, sur l'etat final de la categorie."""
    if not (category.name_fr or category.name_ar):
        raise ValidationError({"non_field_errors": [CATEGORY_NAME_REQUIRED]})


def _ensure_names_are_unique(category: Category) -> None:
    """Unicite insensible a la casse dans la boutique, nom par nom.

    La comparaison reprend l'expression des contraintes UNIQUE (`lower(...)`) ;
    un nom vide ne compte pas.
    """
    others = Category.objects.filter(shop_id=category.shop_id)
    if category.pk is not None:
        others = others.exclude(pk=category.pk)
    errors = {}
    for field in CATEGORY_NAME_FIELDS:
        value = getattr(category, field)
        if not value:
            continue
        duplicates = others.alias(normalized=Lower(field)).filter(normalized=Lower(Value(value)))
        if duplicates.exists():
            errors[field] = [CATEGORY_NAME_DUPLICATE]
    if errors:
        raise ValidationError(errors)


def _duplicate_field(error: IntegrityError) -> str | None:
    """Nom du champ vise par une violation d'unicite, d'apres la contrainte."""
    diag = getattr(error.__cause__, "diag", None)
    return UNIQUE_CONSTRAINT_FIELDS.get(getattr(diag, "constraint_name", None))


def _save_category(category: Category, update_fields: list[str] | None = None) -> Category:
    """Enregistre ; un doublon concurrent (contrainte UNIQUE) devient une erreur 400."""
    try:
        with transaction.atomic():
            category.save(update_fields=update_fields)
    except IntegrityError as error:
        field = _duplicate_field(error)
        if field is None:
            raise
        raise ValidationError({field: [CATEGORY_NAME_DUPLICATE]}) from None
    return category


def create_category(shop: Shop, data: dict[str, Any]) -> Category:
    """Cree une categorie dans la boutique.

    Regles : noms debarrasses des espaces, au moins un nom, unicite insensible a
    la casse de `name_fr` et de `name_ar` dans la boutique, 100 categories au
    maximum. La ligne de la boutique est verrouillee pour que deux creations
    simultanees ne depassent pas la limite.

    Leve LimitReached (409, `details = {"limit": 100}`) et ValidationError (400).
    """
    with transaction.atomic():
        Shop.objects.select_for_update().filter(pk=shop.pk).values_list("pk").get()
        if Category.objects.filter(shop=shop).count() >= MAX_CATEGORIES:
            raise LimitReached(details={"limit": MAX_CATEGORIES})
        category = Category(shop=shop)
        _apply_fields(category, data)
        _ensure_has_name(category)
        _ensure_names_are_unique(category)
        category = _save_category(category)
    logger.info("Categorie %s creee pour la boutique %s", category.pk, shop.pk)
    return category


def update_category(category: Category, data: dict[str, Any]) -> Category:
    """Modifie les noms et/ou l'ordre d'affichage d'une categorie.

    Les regles de `create_category` s'appliquent a l'etat final : un PATCH qui
    vide le seul nom renseigne est refuse.

    Leve ValidationError (400).
    """
    with transaction.atomic():
        category = Category.objects.select_for_update().get(pk=category.pk)
        _apply_fields(category, data)
        _ensure_has_name(category)
        _ensure_names_are_unique(category)
        fields = sorted(CATEGORY_FIELDS & set(data))
        return _save_category(category, update_fields=fields) if fields else category


def delete_category(category: Category) -> None:
    """Supprime une categorie ; ses produits deviennent sans categorie (RG-32).

    Aucun produit n'est supprime : la cle etrangere passe a NULL (SET NULL).
    """
    category_id = category.pk
    with transaction.atomic():
        category.delete()
    logger.info("Categorie %s supprimee", category_id)
