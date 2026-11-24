"""Lectures du dashboard administrateur. Voir 03-reference-api.md section 11.

Aucune ecriture ici : uniquement des querysets filtres et des agregats.
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, F, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import AuditAction, AuditLog
from apps.core.text import normalize_search_text
from apps.orders.models import Order
from apps.shops.models import Shop, ShopState

from .models import Recharge

EXPIRING_SOON_DAYS = 7
EXPIRING_SOON_LIMIT = 20
LATEST_SUBMISSIONS_LIMIT = 5
RECENT_AUDIT_LIMIT = 20
MAX_SEARCH_WORDS = 5

# Tri de la liste des boutiques : valeur du parametre -> expressions ORDER BY.
# Les dates absentes (boutique non soumise, non validee) passent toujours en dernier.
SHOP_ORDERINGS: dict[str, tuple] = {
    "-submitted_at": (F("submitted_at").desc(nulls_last=True),),
    "submitted_at": (F("submitted_at").asc(nulls_last=True),),
    "expires_at": (F("expires_at").asc(nulls_last=True),),
    "-expires_at": (F("expires_at").desc(nulls_last=True),),
    "name": (F("name").asc(),),
    "-created_at": (F("created_at").desc(),),
}
DEFAULT_SHOP_ORDERING = "-submitted_at"

PRODUCT_ORDERINGS = ("created_at", "-created_at", "price", "-price", "name_fr", "-name_fr")
DEFAULT_PRODUCT_ORDERING = "-created_at"


def _local_tz() -> ZoneInfo:
    return ZoneInfo(settings.TIME_ZONE)


def local_day_start(day: date) -> datetime:
    """Debut d'une journee dans le fuseau metier (Africa/Nouakchott)."""
    return datetime.combine(day, time.min, tzinfo=_local_tz())


def filter_by_local_dates(
    queryset: QuerySet, field: str, date_from: date | None, date_to: date | None
) -> QuerySet:
    """Filtre un champ date-heure par jours calendaires locaux, bornes incluses."""
    if date_from is not None:
        queryset = queryset.filter(**{f"{field}__gte": local_day_start(date_from)})
    if date_to is not None:
        queryset = queryset.filter(**{f"{field}__lt": local_day_start(date_to + timedelta(days=1))})
    return queryset


# --- Tableau de bord ----------------------------------------------------------------
def shop_state_counts(now: datetime | None = None) -> dict[str, int]:
    """Nombre de boutiques par etat calcule, plus le total."""
    rows = (
        Shop.objects.with_state(now).order_by().values("computed_state").annotate(count=Count("id"))
    )
    counts = {state.lower(): 0 for state in ShopState.values}
    for row in rows:
        counts[row["computed_state"].lower()] = row["count"]
    counts["total"] = sum(counts.values())
    return counts


def expiring_soon_shops(now: datetime | None = None) -> QuerySet:
    """Boutiques ACTIVE qui expirent dans les 7 jours, de la plus urgente a la moins urgente."""
    now = now or timezone.now()
    return (
        Shop.objects.active(now)
        .filter(expires_at__lte=now + timedelta(days=EXPIRING_SOON_DAYS))
        .order_by("expires_at", "id")[:EXPIRING_SOON_LIMIT]
    )


def month_recharges(now: datetime | None = None) -> dict[str, Any]:
    """Recharges du mois en cours (fuseau metier) : nombre et montant recu."""
    local_now = (now or timezone.now()).astimezone(_local_tz())
    month_start = local_day_start(local_now.date().replace(day=1))
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    totals = Recharge.objects.filter(
        created_at__gte=month_start, created_at__lt=next_month
    ).aggregate(count=Count("id"), amount_received=Coalesce(Sum("amount_received"), 0))
    return {"month": f"{local_now:%Y-%m}", **totals}


def latest_submissions(now: datetime | None = None) -> QuerySet:
    """5 dernieres boutiques en attente de validation."""
    return (
        Shop.objects.with_state(now)
        .filter(computed_state=ShopState.PENDING)
        .order_by(F("submitted_at").desc(nulls_last=True), "-id")[:LATEST_SUBMISSIONS_LIMIT]
    )


# --- Boutiques ----------------------------------------------------------------------
def admin_shops(
    *,
    states: list[str] | None = None,
    search: str = "",
    ordering: str = DEFAULT_SHOP_ORDERING,
    now: datetime | None = None,
) -> QuerySet:
    """Liste des boutiques pour l'administrateur.

    `states` : etats calcules acceptes (annotation computed_state).
    `search` : nom, e-mail, telephone ou nom du proprietaire, insensible a la
    casse et aux accents (extension unaccent).
    """
    queryset = Shop.objects.with_state(now).select_related("owner")
    if states:
        queryset = queryset.filter(computed_state__in=states)
    term = (search or "").strip()
    if term:
        queryset = queryset.filter(
            Q(name__unaccent__icontains=term)
            | Q(owner_full_name__unaccent__icontains=term)
            | Q(owner__email__icontains=term)
            | Q(phone__icontains=term)
            | Q(whatsapp__icontains=term)
        )
    return queryset.order_by(*SHOP_ORDERINGS[ordering], "-id")


def shop_detail_queryset(now: datetime | None = None) -> QuerySet:
    return Shop.objects.with_state(now).select_related("owner", "theme", "approved_by")


def shop_stats(shop: Shop) -> dict[str, int]:
    """Compteurs de la fiche boutique (produits, commandes, revenu des commandes livrees)."""
    products = Product.objects.filter(shop=shop).aggregate(
        products_published=Count("id", filter=Q(status=Product.Status.PUBLISHED)),
        products_draft=Count("id", filter=Q(status=Product.Status.DRAFT)),
    )
    orders = Order.objects.filter(shop=shop).aggregate(
        orders_total=Count("id"),
        orders_delivered=Count("id", filter=Q(status=Order.Status.DELIVERED)),
        revenue_delivered_total=Coalesce(
            Sum("total_amount", filter=Q(status=Order.Status.DELIVERED)), 0
        ),
    )
    return {**products, **orders}


def shop_recent_audit(shop: Shop) -> QuerySet:
    """20 dernieres entrees d'audit de la boutique (y compris ses produits retires)."""
    return (
        AuditLog.objects.filter(
            Q(target_type="shop", target_id=shop.pk)
            | Q(action=AuditAction.PRODUCT_REMOVED_BY_ADMIN, metadata__shop_id=shop.pk)
        )
        .select_related("actor")
        .order_by("-created_at", "-id")[:RECENT_AUDIT_LIMIT]
    )


# --- Recharges ----------------------------------------------------------------------
def recharges(
    *,
    shop_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> QuerySet:
    queryset = Recharge.objects.select_related("shop", "performed_by")
    if shop_id is not None:
        queryset = queryset.filter(shop_id=shop_id)
    queryset = filter_by_local_dates(queryset, "created_at", date_from, date_to)
    return queryset.order_by("-created_at", "-id")


# --- Journal d'audit ----------------------------------------------------------------
def audit_logs(
    *,
    action: str | None = None,
    actor_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> QuerySet:
    queryset = AuditLog.objects.select_related("actor")
    if action:
        queryset = queryset.filter(action=action)
    if actor_id is not None:
        queryset = queryset.filter(actor_id=actor_id)
    if target_type:
        queryset = queryset.filter(target_type=target_type)
    if target_id is not None:
        queryset = queryset.filter(target_id=target_id)
    queryset = filter_by_local_dates(queryset, "created_at", date_from, date_to)
    return queryset.order_by("-created_at", "-id")


# --- Produits (moderation) ----------------------------------------------------------
def shop_products(shop: Shop, filters: dict[str, Any]) -> QuerySet:
    """Produits d'une boutique, avec les memes filtres que GET /shop/products/."""
    queryset = Product.objects.filter(shop=shop).select_related("category")
    words = normalize_search_text(filters.get("search") or "").split()
    for word in [w for w in words if len(w) > 1][:MAX_SEARCH_WORDS]:
        queryset = queryset.filter(
            Q(search_text_fr__contains=word) | Q(search_text_ar__contains=word)
        )
    if filters.get("category") is not None:
        queryset = queryset.filter(category_id=filters["category"])
    if filters.get("uncategorized"):
        queryset = queryset.filter(category__isnull=True)
    for name in ("status", "source"):
        if filters.get(name):
            queryset = queryset.filter(**{name: filters[name]})
    if filters.get("is_available") is not None:
        queryset = queryset.filter(is_available=filters["is_available"])
    if filters.get("import_job") is not None:
        queryset = queryset.filter(import_job_id=filters["import_job"])
    if filters.get("min_price") is not None:
        queryset = queryset.filter(price__gte=filters["min_price"])
    if filters.get("max_price") is not None:
        queryset = queryset.filter(price__lte=filters["max_price"])
    ordering = filters.get("ordering") or DEFAULT_PRODUCT_ORDERING
    return queryset.order_by(ordering, "-id" if ordering.startswith("-") else "id")
