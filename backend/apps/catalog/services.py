"""Ecritures du catalogue de l'espace boutique : categories et produits.

Voir 03-reference-api.md section 6, 04-schema-base-de-donnees.md sections 5.1,
5.2 et 9.5, et 01-vue-d-ensemble.md (RG-30 a RG-32). Les services appliquent
les regles ; les vues ne font qu'appeler.
"""

import logging
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Value
from django.db.models.fields.files import FieldFile
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.core.exceptions import LimitReached
from apps.core.images import process_product_image
from apps.core.storage import delete_file_on_commit
from apps.shops.models import Shop

from .models import Category, ImportJob, Product

logger = logging.getLogger(__name__)

MAX_CATEGORIES = 100
MAX_PRODUCTS = 5000
PRODUCT_NAME_FIELDS = ("name_fr", "name_ar")
PRODUCT_TEXT_FIELDS = frozenset({*PRODUCT_NAME_FIELDS, "description_fr", "description_ar"})
PRODUCT_FIELDS = frozenset({*PRODUCT_TEXT_FIELDS, "price", "category", "status", "is_available"})
PRODUCT_CATEGORY_UNKNOWN = _("Cette catégorie n'existe pas dans votre boutique.")
CATEGORY_NAME_FIELDS = ("name_fr", "name_ar")
CATEGORY_FIELDS = frozenset({*CATEGORY_NAME_FIELDS, "sort_order"})
UNIQUE_CONSTRAINT_FIELDS = {
    "catalog_category_unique_name_fr": "name_fr",
    "catalog_category_unique_name_ar": "name_ar",
}

NAME_REQUIRED = _("Renseignez au moins un nom, en français ou en arabe.")
CATEGORY_NAME_DUPLICATE = _("Une catégorie porte déjà ce nom dans votre boutique.")


def _lock_shop(shop: Shop) -> None:
    """Verrouille la ligne de la boutique (a appeler dans une transaction).

    Deux creations simultanees dans la meme boutique sont ainsi serialisees :
    le controle d'une limite (categories, produits) ne peut pas etre depasse.
    """
    Shop.objects.select_for_update().filter(pk=shop.pk).values_list("pk").get()


def _apply_fields(category: Category, data: dict[str, Any]) -> None:
    """Recopie les champs autorises ; les noms sont debarrasses des espaces."""
    for name, value in data.items():
        if name not in CATEGORY_FIELDS:
            continue
        if name in CATEGORY_NAME_FIELDS:
            value = (value or "").strip()
        setattr(category, name, value)


def _ensure_has_name(item: Category | Product) -> None:
    """Au moins un des deux noms, sur l'etat final de la categorie ou du produit."""
    if not (item.name_fr or item.name_ar):
        raise ValidationError({"non_field_errors": [NAME_REQUIRED]})


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
        _lock_shop(shop)
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


# --- Produits ---------------------------------------------------------------------
def _apply_product_fields(product: Product, data: dict[str, Any]) -> None:
    """Recopie les champs modifiables ; noms et descriptions sans espaces autour.

    Les autres cles (`shop`, `source`, `import_job`, `published_at`...) sont ignorees.
    """
    for name, value in data.items():
        if name not in PRODUCT_FIELDS:
            continue
        if name in PRODUCT_TEXT_FIELDS:
            value = (value or "").strip()
        setattr(product, name, value)


def _ensure_category_in_shop(product: Product) -> None:
    """La categorie doit appartenir a la boutique du produit.

    Une categorie d'une autre boutique donne la meme erreur qu'une categorie
    inexistante : son existence n'est pas divulguee.
    """
    if product.category is not None and product.category.shop_id != product.shop_id:
        raise ValidationError({"category_id": [PRODUCT_CATEGORY_UNKNOWN]})


def _process_image(image_file) -> tuple[ContentFile, ContentFile]:
    """Image principale WebP (1 600 px) + miniature (400 px), sans metadonnees.

    Leve FileTooLarge (413) ou ValidationError (400, champ `image`).
    """
    try:
        processed = process_product_image(image_file)
    except DjangoValidationError as error:
        raise ValidationError({"image": error.messages}) from None
    return processed.image, processed.thumbnail


def _store_images(product: Product, image: ContentFile, thumbnail: ContentFile) -> list[FieldFile]:
    """Ecrit les fichiers sur le stockage (sans enregistrer la ligne).

    Renvoie les fichiers ecrits, a supprimer si l'enregistrement echoue ensuite.
    """
    product.image.save(image.name, image, save=False)
    product.thumbnail.save(thumbnail.name, thumbnail, save=False)
    return [product.image, product.thumbnail]


def _discard_files(files: list[FieldFile]) -> None:
    """Supprime tout de suite des fichiers ecrits pour une operation qui a echoue."""
    for field_file in files:
        try:
            field_file.storage.delete(field_file.name)
        except OSError:
            logger.exception("Fichier orphelin non supprime : %s", field_file.name)


def create_product_from_data(
    shop: Shop,
    data: dict[str, Any],
    image_file,
    *,
    source: str = Product.Source.MANUAL,
    import_job: ImportJob | None = None,
) -> Product:
    """Cree un produit dans la boutique (RG-30, RG-31).

    Reutilisable par l'import (phase 6), qui passe `source="IMPORT"` et le job.
    `data` contient les champs deja valides : `name_fr`, `name_ar`,
    `description_fr`, `description_ar`, `price`, `category` (instance de la
    boutique ou None), `status` (defaut PUBLISHED), `is_available` (defaut true).

    Regles : noms et descriptions debarrasses des espaces, au moins un nom,
    categorie de la boutique, 5 000 produits au maximum (brouillons compris),
    controle avant le traitement de l'image, sous verrou de la boutique.
    `published_at` est rempli si le produit est cree publie. Si l'operation
    echoue apres l'ecriture des images, les fichiers sont supprimes.

    Leve LimitReached (409, `details = {"limit": 5000}`), ValidationError (400)
    et FileTooLarge (413).
    """
    new_files: list[FieldFile] = []
    try:
        with transaction.atomic():
            _lock_shop(shop)
            if Product.objects.filter(shop=shop).count() >= MAX_PRODUCTS:
                raise LimitReached(details={"limit": MAX_PRODUCTS})
            product = Product(shop=shop, source=source, import_job=import_job)
            _apply_product_fields(product, data)
            _ensure_has_name(product)
            _ensure_category_in_shop(product)
            if product.status == Product.Status.PUBLISHED:
                product.published_at = timezone.now()
            image, thumbnail = _process_image(image_file)
            new_files = _store_images(product, image, thumbnail)
            product.save()
    except BaseException:
        _discard_files(new_files)
        raise
    logger.info("Produit %s cree pour la boutique %s (%s)", product.pk, shop.pk, source)
    return product


def update_product(product: Product, data: dict[str, Any], image_file=None) -> Product:
    """Modifie un produit (RG-30, RG-31) ; tous les champs sont facultatifs.

    Les regles de la creation s'appliquent a l'etat final. Passer de DRAFT a
    PUBLISHED remplit `published_at` ; un produit qui reste publie garde sa date,
    et un retour en brouillon la conserve. Une nouvelle image remplace l'ancienne :
    les anciens fichiers sont supprimes apres la validation de la transaction,
    les nouveaux sont supprimes si l'operation echoue.

    Leve ValidationError (400) et FileTooLarge (413).
    """
    new_files: list[FieldFile] = []
    try:
        with transaction.atomic():
            product = (
                Product.objects.select_for_update(of=("self",))
                .select_related("category")
                .get(pk=product.pk)
            )
            was_published = product.status == Product.Status.PUBLISHED
            _apply_product_fields(product, data)
            _ensure_has_name(product)
            _ensure_category_in_shop(product)
            if product.status == Product.Status.PUBLISHED and not was_published:
                product.published_at = timezone.now()
            if image_file is not None:
                image, thumbnail = _process_image(image_file)
                delete_file_on_commit(product.image)
                delete_file_on_commit(product.thumbnail)
                new_files = _store_images(product, image, thumbnail)
            product.save()
    except BaseException:
        _discard_files(new_files)
        raise
    return product


def delete_product(product: Product) -> None:
    """Supprime un produit (suppression physique, 04 section 9.5).

    Les lignes de commande gardent leurs copies (`product_id` passe a NULL). Les
    fichiers image sont supprimes apres la validation de la transaction par le
    signal `post_delete` (apps/catalog/signals.py).
    """
    product_id = product.pk
    with transaction.atomic():
        product.delete()
    logger.info("Produit %s supprime", product_id)


# --- Actions groupees -------------------------------------------------------------
BULK_MAX_IDS = 1000
SKIP_NOT_FOUND = "NOT_FOUND"
SKIP_ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
BULK_UPDATE_FIELDS = frozenset({"category", "is_available"})
BULK_UPDATE_NOTHING = _("Indiquez au moins un champ à modifier : category_id ou is_available.")


def bulk_publish_products(shop: Shop, ids: list[int]) -> dict[str, list]:
    """Publie les brouillons choisis (« Publier la selection », RG-35, liste 1).

    `ids` est deja valide et dedoublonne (1 a 1 000 entiers). Seuls les produits
    de `shop` sont lus : un identifiant inexistant ou d'une autre boutique est
    renvoye dans `skipped` avec la raison NOT_FOUND (meme raison dans les deux
    cas : aucune divulgation). Un produit deja publie est renvoye avec
    ALREADY_PUBLISHED et garde son `published_at`. Les brouillons passent en
    PUBLISHED avec le meme `published_at` et le meme `updated_at` ; `is_available`
    et les textes ne changent pas. Les listes suivent l'ordre de `ids`.

    Nombre de requetes constant : une lecture sous verrou, une mise a jour.
    Aucune exception metier : la reponse decrit le sort de chaque identifiant.
    """
    with transaction.atomic():
        statuses = dict(
            Product.objects.select_for_update()
            .filter(shop=shop, id__in=ids)
            .values_list("id", "status")
        )
        drafts = [pk for pk in ids if statuses.get(pk) == Product.Status.DRAFT]
        if drafts:
            now = timezone.now()
            Product.objects.filter(shop=shop, id__in=drafts).update(
                status=Product.Status.PUBLISHED, published_at=now, updated_at=now
            )
    skipped = [
        {"id": pk, "reason": SKIP_NOT_FOUND if pk not in statuses else SKIP_ALREADY_PUBLISHED}
        for pk in ids
        if statuses.get(pk) != Product.Status.DRAFT
    ]
    logger.info("Boutique %s : %s produit(s) publie(s) en groupe", shop.pk, len(drafts))
    return {"published_ids": drafts, "skipped": skipped}


def bulk_update_products(shop: Shop, ids: list[int], data: dict[str, Any]) -> int:
    """Change la categorie et/ou la disponibilite des produits choisis.

    `data` contient `category` (instance de la boutique ou None : sans categorie)
    et/ou `is_available` ; une cle absente ne change pas. Le statut,
    `published_at` et les textes ne sont jamais modifies ici.

    Traitement partiel (decision du responsable de la phase 5) : seuls les
    produits de `shop` sont mis a jour ; un identifiant inexistant ou d'une autre
    boutique est ignore, sans distinction (aucune divulgation). Renvoie le nombre
    de produits de la boutique trouves et mis a jour, meme si la valeur etait
    deja identique (0 si aucun). Une seule requete UPDATE, `updated_at` compris.

    Leve ValidationError (400, `category_id`) si la categorie n'est pas de la
    boutique (controle de defense : le serializer l'a deja verifie).
    """
    fields = {name: value for name, value in data.items() if name in BULK_UPDATE_FIELDS}
    category = fields.get("category")
    if category is not None and category.shop_id != shop.pk:
        raise ValidationError({"category_id": [PRODUCT_CATEGORY_UNKNOWN]})
    with transaction.atomic():
        updated = Product.objects.filter(shop=shop, id__in=ids).update(
            **fields, updated_at=timezone.now()
        )
    logger.info("Boutique %s : %s produit(s) modifie(s) en groupe", shop.pk, updated)
    return updated


def bulk_delete_products(shop: Shop, ids: list[int]) -> int:
    """Supprime les produits choisis (suppression physique, 04 section 9.5).

    Traitement partiel (decision du responsable de la phase 5) : seuls les
    produits de `shop` sont supprimes ; un identifiant inexistant ou d'une autre
    boutique est ignore, sans distinction. Les lignes de commande gardent leurs
    copies (`product_id` passe a NULL). Le signal `post_delete` supprime image et
    miniature de chaque produit apres la validation de la transaction : une
    transaction annulee ne supprime aucun fichier.

    Renvoie le nombre de produits supprimes (objets lies non comptes, 0 si aucun).
    """
    with transaction.atomic():
        _total, per_model = Product.objects.filter(shop=shop, id__in=ids).delete()
    deleted = per_model.get(Product._meta.label, 0)
    logger.info("Boutique %s : %s produit(s) supprime(s) en groupe", shop.pk, deleted)
    return deleted
