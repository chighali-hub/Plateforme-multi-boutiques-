"""Validation des entrees et format des sorties de l'espace boutique.

Voir 03-reference-api.md section 5. Aucune regle metier ici : les services s'en chargent.
"""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import ImageUploadField, PhoneField
from apps.administration.models import Recharge
from apps.core.i18n import normalize_language
from apps.core.images import process_logo, sanitize_private_image
from apps.core.validators import normalize_hex_color

from .models import BankAccount, Shop, ShopState, ThemeTemplate

THEME_UNAVAILABLE = _("Ce modèle de design n'existe pas ou n'est plus proposé.")
ID_CARD_REQUIRED = _("Envoyez au moins une face de la carte d'identité.")
TERMS_REQUIRED = _("Vous devez accepter les conditions pour continuer.")

# Matrice 03-reference-api.md section 0.3, exposee au front dans ShopProfile.permissions.
PERMISSION_STATES: dict[str, frozenset[str]] = {
    "can_edit_profile": frozenset({ShopState.REJECTED, ShopState.ACTIVE}),
    "can_edit_id_card": frozenset({ShopState.REJECTED}),
    "can_resubmit": frozenset({ShopState.REJECTED}),
    "can_manage_catalog": frozenset({ShopState.ACTIVE}),
    "can_manage_orders": frozenset({ShopState.ACTIVE}),
}


def _absolute(request, url: str) -> str:
    return request.build_absolute_uri(url) if request else url


class HexColorField(serializers.CharField):
    """Couleur #RRGGBB, renvoyee en majuscules."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 7)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalize_hex_color(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages) from None


# --- Sorties ----------------------------------------------------------------------
class ThemeSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    preview_image_url = serializers.SerializerMethodField()

    class Meta:
        model = ThemeTemplate
        fields = [
            "id",
            "code",
            "name",
            "name_fr",
            "name_ar",
            "layout",
            "preview_image_url",
            "default_primary_color",
            "default_accent_color",
        ]

    def get_name(self, theme: ThemeTemplate) -> str:
        """Nom dans la langue de la requete."""
        return theme.name_ar if normalize_language(get_language()) == "ar" else theme.name_fr

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_preview_image_url(self, theme: ThemeTemplate) -> str | None:
        if not theme.preview_image:
            return None
        return _absolute(self.context.get("request"), theme.preview_image.url)


class ShopPermissionsSerializer(serializers.Serializer):
    can_edit_profile = serializers.BooleanField()
    can_edit_id_card = serializers.BooleanField()
    can_resubmit = serializers.BooleanField()
    can_manage_catalog = serializers.BooleanField()
    can_manage_orders = serializers.BooleanField()


class ShopProfileSerializer(serializers.ModelSerializer):
    """Objet ShopProfile (03-reference-api.md section 5)."""

    email = serializers.EmailField(source="owner.email", read_only=True)
    logo_url = serializers.SerializerMethodField()
    theme = ThemeSerializer(read_only=True, allow_null=True)
    state = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()
    id_card_front_url = serializers.SerializerMethodField()
    id_card_back_url = serializers.SerializerMethodField()
    banks_count = serializers.SerializerMethodField()
    is_publicly_visible = serializers.SerializerMethodField()
    public_url = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = [
            "id",
            "name",
            "slug",
            "email",
            "logo_url",
            "description_fr",
            "description_ar",
            "address",
            "phone",
            "whatsapp",
            "owner_full_name",
            "theme",
            "primary_color",
            "accent_color",
            "onboarding_step",
            "status",
            "state",
            "rejection_reason",
            "submitted_at",
            "approved_at",
            "expires_at",
            "days_left",
            "id_card_front_url",
            "id_card_back_url",
            "banks_count",
            "is_publicly_visible",
            "public_url",
            "permissions",
            "created_at",
        ]
        read_only_fields = fields

    def _state(self, shop: Shop) -> str:
        # Un seul calcul par serialisation : l'heure ne bouge pas entre deux champs.
        cache = self.context.setdefault("_shop_states", {})
        if shop.pk not in cache:
            cache[shop.pk] = shop.get_state()
        return cache[shop.pk]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, shop: Shop) -> str | None:
        if not shop.logo:
            return None
        return _absolute(self.context.get("request"), shop.logo.url)

    @extend_schema_field(serializers.ChoiceField(choices=ShopState.choices))
    def get_state(self, shop: Shop) -> str:
        return self._state(shop)

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_days_left(self, shop: Shop) -> int | None:
        """Jours entiers restants (arrondi superieur), 0 si expiree, null sans date."""
        if shop.expires_at is None:
            return None
        return shop.days_left()

    def _id_card_url(self, side: str) -> str:
        path = reverse("shops-me-id-card", kwargs={"side": side})
        return _absolute(self.context.get("request"), path)

    @extend_schema_field(serializers.URLField())
    def get_id_card_front_url(self, shop: Shop) -> str:
        return self._id_card_url("front")

    @extend_schema_field(serializers.URLField())
    def get_id_card_back_url(self, shop: Shop) -> str:
        return self._id_card_url("back")

    def get_banks_count(self, shop: Shop) -> int:
        return shop.bank_accounts.count()

    def get_is_publicly_visible(self, shop: Shop) -> bool:
        """RG-40 : etat ACTIVE et au moins une banque."""
        return self._state(shop) == ShopState.ACTIVE and shop.bank_accounts.exists()

    @extend_schema_field(serializers.URLField())
    def get_public_url(self, shop: Shop) -> str:
        return f"{settings.FRONTEND_URL.rstrip('/')}/boutiques/{shop.slug}"

    @extend_schema_field(ShopPermissionsSerializer)
    def get_permissions(self, shop: Shop) -> dict[str, bool]:
        state = self._state(shop)
        return {name: state in states for name, states in PERMISSION_STATES.items()}


class BankAccountSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(min_length=2, max_length=60)
    payment_code = serializers.CharField(min_length=2, max_length=40)

    class Meta:
        model = BankAccount
        fields = ["id", "bank_name", "payment_code", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        # L'unicite (banque, code) est controlee par le service, dans la boutique.
        validators: list = []


class ShopRechargeSerializer(serializers.ModelSerializer):
    """Recharge vue par la boutique : sans montant recu ni note (reserves a l'admin)."""

    class Meta:
        model = Recharge
        fields = ["id", "duration_months", "previous_expires_at", "new_expires_at", "created_at"]
        read_only_fields = fields


class RechargeInfoSerializer(serializers.Serializer):
    expires_at = serializers.DateTimeField(allow_null=True)
    days_left = serializers.IntegerField(allow_null=True)
    admin_whatsapp = serializers.CharField()
    whatsapp_url = serializers.CharField()
    admin_contact_email = serializers.CharField()


# --- Entrees ----------------------------------------------------------------------
class DesignSerializer(serializers.Serializer):
    """Choix du design : modele actif, couleurs facultatives (defaut : celles du modele)."""

    theme_id = serializers.PrimaryKeyRelatedField(
        queryset=ThemeTemplate.objects.filter(is_active=True),
        source="theme",
        error_messages={
            "does_not_exist": THEME_UNAVAILABLE,
            "incorrect_type": THEME_UNAVAILABLE,
        },
    )
    primary_color = HexColorField(required=False)
    accent_color = HexColorField(required=False)


class AcceptTermsSerializer(serializers.Serializer):
    accept_terms = serializers.BooleanField()

    def validate_accept_terms(self, value: bool) -> bool:
        if value is not True:
            raise serializers.ValidationError(TERMS_REQUIRED)
        return value


class ShopProfileUpdateSerializer(serializers.Serializer):
    """PATCH /shop/me/ : tous les champs sont facultatifs."""

    name = serializers.CharField(min_length=2, max_length=80, required=False)
    logo = ImageUploadField(required=False)
    description_fr = serializers.CharField(min_length=10, max_length=500, required=False)
    description_ar = serializers.CharField(min_length=10, max_length=500, required=False)
    address = serializers.CharField(min_length=5, max_length=255, required=False)
    phone = PhoneField(required=False)
    whatsapp = PhoneField(required=False)
    owner_full_name = serializers.CharField(min_length=3, max_length=120, required=False)

    def profile_fields(self) -> dict[str, str]:
        return {name: value for name, value in self.validated_data.items() if name != "logo"}

    def processed_logo(self):
        """Logo converti en WebP (512 px max, sans metadonnees), ou None."""
        logo = self.validated_data.get("logo")
        return process_logo(logo) if logo is not None else None


class IdCardSerializer(serializers.Serializer):
    """PUT /shop/me/id-card/ : au moins une des deux faces."""

    id_card_front = ImageUploadField(required=False)
    id_card_back = ImageUploadField(required=False)

    def validate(self, attrs):
        if not attrs.get("id_card_front") and not attrs.get("id_card_back"):
            raise serializers.ValidationError({"non_field_errors": [ID_CARD_REQUIRED]})
        return attrs

    def processed_files(self) -> dict:
        """Faces nettoyees (metadonnees supprimees, qualite conservee)."""
        return {
            key: sanitize_private_image(upload) if upload else None
            for key, upload in (
                ("front", self.validated_data.get("id_card_front")),
                ("back", self.validated_data.get("id_card_back")),
            )
        }
