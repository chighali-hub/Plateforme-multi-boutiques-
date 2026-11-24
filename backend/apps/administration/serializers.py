"""Validation des entrees et format des sorties du dashboard administrateur.

Voir 03-reference-api.md sections 10 (platform-info) et 11. Aucune regle metier
ici : les services s'en chargent.
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import PhoneField
from apps.catalog.models import Product
from apps.core.models import AuditAction, AuditLog, PlatformSettings
from apps.core.whatsapp import build_whatsapp_url
from apps.shops.models import BankAccount, Shop, ShopState
from apps.shops.serializers import ThemeSerializer

from . import selectors
from .models import RECHARGE_MONTHS_MAX, RECHARGE_MONTHS_MIN, Recharge

ONE_RECHARGE_MODE = _("Indiquez soit une durée en mois, soit une date cible, mais pas les deux.")
DATE_RANGE_INVALID = _("La date de début doit précéder la date de fin.")
PRICE_RANGE_INVALID = _("Le prix minimum doit être inférieur ou égal au prix maximum.")
STATE_UNKNOWN = _("État inconnu : %(value)s.")


def _absolute(request, url: str) -> str:
    return request.build_absolute_uri(url) if request else url


def _file_url(request, field_file) -> str | None:
    if not field_file:
        return None
    return _absolute(request, field_file.url)


class UserRefSerializer(serializers.Serializer):
    """Reference courte a un utilisateur : {id, email}."""

    id = serializers.IntegerField()
    email = serializers.EmailField()


# --- Boutiques ----------------------------------------------------------------------
class AdminShopSummarySerializer(serializers.ModelSerializer):
    """Objet AdminShopSummary (03-reference-api.md section 11)."""

    logo_url = serializers.SerializerMethodField()
    email = serializers.EmailField(source="owner.email", read_only=True)
    state = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = [
            "id",
            "name",
            "slug",
            "logo_url",
            "owner_full_name",
            "email",
            "phone",
            "state",
            "is_blocked",
            "submitted_at",
            "approved_at",
            "expires_at",
            "days_left",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, shop: Shop) -> str | None:
        return _file_url(self.context.get("request"), shop.logo)

    @extend_schema_field(serializers.ChoiceField(choices=ShopState.choices))
    def get_state(self, shop: Shop) -> str:
        """Etat calcule : annotation `computed_state` si presente (un seul instant)."""
        return getattr(shop, "computed_state", None) or shop.get_state()

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_days_left(self, shop: Shop) -> int | None:
        """Jours entiers restants (arrondi superieur), 0 si expiree, null sans date."""
        if shop.expires_at is None:
            return None
        return shop.days_left()


class AdminBankSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ["id", "bank_name", "payment_code"]
        read_only_fields = fields


class ShopStatsSerializer(serializers.Serializer):
    products_published = serializers.IntegerField()
    products_draft = serializers.IntegerField()
    orders_total = serializers.IntegerField()
    orders_delivered = serializers.IntegerField()
    revenue_delivered_total = serializers.IntegerField()


class RecentAuditSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["action", "actor_email", "metadata", "created_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_actor_email(self, entry: AuditLog) -> str | None:
        return entry.actor.email if entry.actor_id else None


class AdminShopDetailSerializer(AdminShopSummarySerializer):
    """AdminShopSummary + fiche complete (carte d'identite, banques, stats, audit)."""

    whatsapp_url = serializers.SerializerMethodField()
    theme = ThemeSerializer(read_only=True, allow_null=True)
    approved_by = serializers.SerializerMethodField()
    id_card_front_url = serializers.SerializerMethodField()
    id_card_back_url = serializers.SerializerMethodField()
    banks = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()
    recent_audit = serializers.SerializerMethodField()

    class Meta(AdminShopSummarySerializer.Meta):
        fields = [
            *AdminShopSummarySerializer.Meta.fields,
            "description_fr",
            "description_ar",
            "address",
            "whatsapp",
            "whatsapp_url",
            "theme",
            "primary_color",
            "accent_color",
            "onboarding_step",
            "status",
            "rejection_reason",
            "rejected_at",
            "block_reason",
            "blocked_at",
            "approved_by",
            "id_card_front_url",
            "id_card_back_url",
            "banks",
            "stats",
            "recent_audit",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField())
    def get_whatsapp_url(self, shop: Shop) -> str:
        return build_whatsapp_url(shop.whatsapp)

    @extend_schema_field(UserRefSerializer(allow_null=True))
    def get_approved_by(self, shop: Shop) -> dict | None:
        if shop.approved_by_id is None:
            return None
        return {"id": shop.approved_by.pk, "email": shop.approved_by.email}

    def _id_card_url(self, shop: Shop, side: str) -> str:
        path = reverse("administration-shops-id-card", kwargs={"pk": shop.pk, "side": side})
        return _absolute(self.context.get("request"), path)

    @extend_schema_field(serializers.URLField())
    def get_id_card_front_url(self, shop: Shop) -> str:
        return self._id_card_url(shop, "front")

    @extend_schema_field(serializers.URLField())
    def get_id_card_back_url(self, shop: Shop) -> str:
        return self._id_card_url(shop, "back")

    @extend_schema_field(AdminBankSerializer(many=True))
    def get_banks(self, shop: Shop) -> list[dict]:
        banks = BankAccount.objects.filter(shop=shop).order_by("id")
        return AdminBankSerializer(banks, many=True).data

    @extend_schema_field(ShopStatsSerializer)
    def get_stats(self, shop: Shop) -> dict[str, int]:
        return selectors.shop_stats(shop)

    @extend_schema_field(RecentAuditSerializer(many=True))
    def get_recent_audit(self, shop: Shop) -> list[dict]:
        return RecentAuditSerializer(selectors.shop_recent_audit(shop), many=True).data


class AdminShopListQuerySerializer(serializers.Serializer):
    state = serializers.CharField(required=False, allow_blank=True)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    ordering = serializers.ChoiceField(
        choices=list(selectors.SHOP_ORDERINGS),
        required=False,
        default=selectors.DEFAULT_SHOP_ORDERING,
    )

    def validate_state(self, value: str) -> list[str]:
        """Un ou plusieurs etats separes par des virgules : ACTIVE,EXPIRED."""
        states = [part.strip().upper() for part in value.split(",") if part.strip()]
        for state in states:
            if state not in ShopState.values:
                raise serializers.ValidationError(STATE_UNKNOWN % {"value": state})
        return list(dict.fromkeys(states))


class ReasonSerializer(serializers.Serializer):
    """Motif d'un blocage ou d'un retrait de produit : 5 a 500 caracteres."""

    reason = serializers.CharField(min_length=5, max_length=500)


class RejectSerializer(serializers.Serializer):
    """Motif d'un refus : 10 a 500 caracteres (RG-12)."""

    reason = serializers.CharField(min_length=10, max_length=500)


# --- Tableau de bord ----------------------------------------------------------------
class DashboardShopCountsSerializer(serializers.Serializer):
    onboarding = serializers.IntegerField()
    pending = serializers.IntegerField()
    active = serializers.IntegerField()
    rejected = serializers.IntegerField()
    expired = serializers.IntegerField()
    blocked = serializers.IntegerField()
    total = serializers.IntegerField()


class ExpiringShopSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    whatsapp_url = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = ["id", "name", "logo_url", "phone", "whatsapp_url", "expires_at", "days_left"]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, shop: Shop) -> str | None:
        return _file_url(self.context.get("request"), shop.logo)

    @extend_schema_field(serializers.URLField())
    def get_whatsapp_url(self, shop: Shop) -> str:
        return build_whatsapp_url(shop.whatsapp)

    def get_days_left(self, shop: Shop) -> int:
        return shop.days_left()


class DashboardRechargesSerializer(serializers.Serializer):
    month = serializers.CharField()
    count = serializers.IntegerField()
    amount_received = serializers.IntegerField()


class SubmissionSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = ["id", "name", "logo_url", "submitted_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, shop: Shop) -> str | None:
        return _file_url(self.context.get("request"), shop.logo)


class AdminDashboardSerializer(serializers.Serializer):
    shops = DashboardShopCountsSerializer()
    expiring_soon = ExpiringShopSerializer(many=True)
    recharges = DashboardRechargesSerializer()
    latest_submissions = SubmissionSerializer(many=True)


# --- Recharges ----------------------------------------------------------------------
class RechargeSerializer(serializers.ModelSerializer):
    """Recharge vue par l'administrateur (avec montant recu et note)."""

    performed_by = serializers.SerializerMethodField()

    class Meta:
        model = Recharge
        fields = [
            "id",
            "duration_months",
            "previous_expires_at",
            "new_expires_at",
            "amount_received",
            "note",
            "performed_by",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(UserRefSerializer(allow_null=True))
    def get_performed_by(self, recharge: Recharge) -> dict | None:
        if recharge.performed_by_id is None:
            return None
        return {"id": recharge.performed_by.pk, "email": recharge.performed_by.email}


class ShopRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class RechargeWithShopSerializer(RechargeSerializer):
    """Element de GET /admin/recharges/ : la recharge et sa boutique {id, name}."""

    shop = ShopRefSerializer(read_only=True)

    class Meta(RechargeSerializer.Meta):
        fields = [*RechargeSerializer.Meta.fields, "shop"]
        read_only_fields = fields


class RechargeResultSerializer(serializers.Serializer):
    recharge = RechargeSerializer()
    shop = AdminShopSummarySerializer()


class RechargeModeSerializer(serializers.Serializer):
    """Exactement un parmi duration_months (1 a 120) et target_date (AAAA-MM-JJ)."""

    duration_months = serializers.IntegerField(
        min_value=RECHARGE_MONTHS_MIN, max_value=RECHARGE_MONTHS_MAX, required=False
    )
    target_date = serializers.DateField(required=False)

    def validate(self, attrs):
        if ("duration_months" in attrs) == ("target_date" in attrs):
            raise serializers.ValidationError({"non_field_errors": [ONE_RECHARGE_MODE]})
        return attrs


class RechargePreviewSerializer(serializers.Serializer):
    current_expires_at = serializers.DateTimeField()
    base_date = serializers.DateTimeField()
    new_expires_at = serializers.DateTimeField()
    is_currently_expired = serializers.BooleanField()


class RechargeCreateSerializer(RechargeModeSerializer):
    amount_received = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class DateRangeQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        date_from, date_to = attrs.get("date_from"), attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError({"date_from": [DATE_RANGE_INVALID]})
        return attrs


class RechargeListQuerySerializer(DateRangeQuerySerializer):
    shop = serializers.IntegerField(min_value=1, required=False)


# --- Produits (moderation) ----------------------------------------------------------
class ProductCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name_fr = serializers.CharField()
    name_ar = serializers.CharField()


class AdminProductSerializer(serializers.ModelSerializer):
    """Objet Product (03-reference-api.md section 6)."""

    category = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    import_job_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Product
        fields = [
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
        ]
        read_only_fields = fields

    @extend_schema_field(ProductCategorySerializer(allow_null=True))
    def get_category(self, product: Product) -> dict | None:
        if product.category_id is None:
            return None
        category = product.category
        return {"id": category.pk, "name_fr": category.name_fr, "name_ar": category.name_ar}

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, product: Product) -> str | None:
        return _file_url(self.context.get("request"), product.image)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_thumbnail_url(self, product: Product) -> str | None:
        return _file_url(self.context.get("request"), product.thumbnail)


class ProductListQuerySerializer(serializers.Serializer):
    """Memes filtres que GET /shop/products/ (03-reference-api.md section 6)."""

    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    category = serializers.IntegerField(min_value=1, required=False)
    uncategorized = serializers.ChoiceField(choices=["true"], required=False)
    status = serializers.ChoiceField(choices=Product.Status.choices, required=False)
    is_available = serializers.ChoiceField(choices=["true", "false"], required=False)
    source = serializers.ChoiceField(choices=Product.Source.choices, required=False)
    import_job = serializers.IntegerField(min_value=1, required=False)
    min_price = serializers.IntegerField(min_value=0, required=False)
    max_price = serializers.IntegerField(min_value=0, required=False)
    ordering = serializers.ChoiceField(
        choices=list(selectors.PRODUCT_ORDERINGS),
        required=False,
        default=selectors.DEFAULT_PRODUCT_ORDERING,
    )

    def validate(self, attrs):
        min_price, max_price = attrs.get("min_price"), attrs.get("max_price")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise serializers.ValidationError({"min_price": [PRICE_RANGE_INVALID]})
        if "uncategorized" in attrs:
            attrs["uncategorized"] = True
        if "is_available" in attrs:
            attrs["is_available"] = attrs["is_available"] == "true"
        return attrs


# --- Parametres de la plateforme ----------------------------------------------------
class PlatformSettingsSerializer(serializers.ModelSerializer):
    admin_whatsapp = PhoneField(required=False)
    admin_contact_email = serializers.EmailField(max_length=254, required=False)
    trial_months = serializers.IntegerField(min_value=0, max_value=12, required=False)
    deposit_percent = serializers.IntegerField(min_value=1, max_value=100, required=False)
    updated_by = serializers.SerializerMethodField()

    class Meta:
        model = PlatformSettings
        fields = [
            "admin_whatsapp",
            "admin_contact_email",
            "trial_months",
            "deposit_percent",
            "updated_at",
            "updated_by",
        ]
        read_only_fields = ["updated_at", "updated_by"]

    def validate_admin_contact_email(self, value: str) -> str:
        return value.strip().lower()

    @extend_schema_field(UserRefSerializer(allow_null=True))
    def get_updated_by(self, platform: PlatformSettings) -> dict | None:
        if platform.updated_by_id is None:
            return None
        return {"id": platform.updated_by.pk, "email": platform.updated_by.email}


class PlatformInfoSerializer(serializers.Serializer):
    admin_whatsapp = serializers.CharField()
    admin_whatsapp_url = serializers.CharField()
    admin_contact_email = serializers.CharField()
    deposit_percent = serializers.IntegerField()


# --- Journal d'audit ----------------------------------------------------------------
class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "action",
            "actor",
            "target_type",
            "target_id",
            "metadata",
            "ip_address",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(UserRefSerializer(allow_null=True))
    def get_actor(self, entry: AuditLog) -> dict | None:
        if entry.actor_id is None:
            return None
        return {"id": entry.actor.pk, "email": entry.actor.email}


class AuditLogQuerySerializer(DateRangeQuerySerializer):
    action = serializers.ChoiceField(choices=AuditAction.choices, required=False)
    actor = serializers.IntegerField(min_value=1, required=False)
    target_type = serializers.CharField(required=False, allow_blank=True, max_length=50)
    target_id = serializers.IntegerField(min_value=1, required=False)
