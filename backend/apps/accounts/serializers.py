"""Validation des entrees et format des sorties de l'authentification.

Voir 03-reference-api.md sections 3 et 4. Les serializers ne contiennent
aucune regle metier : ils valident puis passent la main aux services.
"""

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.images import process_logo, sanitize_private_image
from apps.core.validators import normalize_phone, validate_image_file
from apps.shops.models import Shop

from .models import OtpCode, User
from .services import RegistrationFiles

OTP_CODE_FIELD_KWARGS = {
    "min_length": 6,
    "max_length": 6,
    "error_messages": {
        "min_length": _("Le code comporte 6 chiffres."),
        "max_length": _("Le code comporte 6 chiffres."),
    },
}
PASSWORDS_DIFFER = _("Les deux mots de passe ne correspondent pas.")


class OtpCodeField(serializers.RegexField):
    def __init__(self, **kwargs):
        super().__init__(r"^[0-9]{6}$", **OTP_CODE_FIELD_KWARGS, **kwargs)
        self.error_messages["invalid"] = _("Le code comporte 6 chiffres.")


class PhoneField(serializers.CharField):
    """Telephone mauritanien, normalise sur 8 chiffres."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 20)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalize_phone(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages) from None


class ImageUploadField(serializers.FileField):
    """Image JPEG, PNG ou WebP reellement decodable, 5 Mo au maximum.

    Un fichier trop gros leve FileTooLarge (413) avec le nom du champ.
    """

    def to_internal_value(self, data):
        upload = super().to_internal_value(data)
        try:
            validate_image_file(upload, field_name=self.field_name)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages) from None
        return upload


def _validate_new_password(password: str, email: str | None, user: User | None = None) -> None:
    probe = user or User(email=email or "")
    try:
        password_validation.validate_password(password, user=probe)
    except DjangoValidationError as error:
        raise serializers.ValidationError({"password": list(error.messages)}) from None


# --- Sorties ----------------------------------------------------------------------
class UserShopSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    state = serializers.CharField(read_only=True)

    class Meta:
        model = Shop
        fields = ["id", "name", "slug", "logo_url", "state", "onboarding_step", "expires_at"]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, shop: Shop) -> str | None:
        if not shop.logo:
            return None
        request = self.context.get("request")
        url = shop.logo.url
        return request.build_absolute_uri(url) if request else url


class UserSerializer(serializers.ModelSerializer):
    shop = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "role", "is_email_verified", "shop"]

    @extend_schema_field(UserShopSerializer(allow_null=True))
    def get_shop(self, user: User):
        if user.role != User.Role.SHOP:
            return None
        shop = Shop.objects.filter(owner=user).first()
        return UserShopSerializer(shop, context=self.context).data if shop else None


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class TokensSerializer(TokenPairSerializer):
    user = UserSerializer()


class RegisterResponseSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_expires_in = serializers.IntegerField()
    resend_available_in = serializers.IntegerField()


class ResendResponseSerializer(serializers.Serializer):
    resend_available_in = serializers.IntegerField()


class ForgotResponseSerializer(serializers.Serializer):
    otp_expires_in = serializers.IntegerField()
    resend_available_in = serializers.IntegerField()


class ResetTokenResponseSerializer(serializers.Serializer):
    reset_token = serializers.CharField()
    expires_in = serializers.IntegerField()


class EmailChangeResponseSerializer(serializers.Serializer):
    sent_to = serializers.EmailField()
    otp_expires_in = serializers.IntegerField()
    resend_available_in = serializers.IntegerField()


# --- Entrees ----------------------------------------------------------------------
class RegisterSerializer(serializers.Serializer):
    """RG-01 : tous les champs sont obligatoires."""

    shop_name = serializers.CharField(min_length=2, max_length=80)
    logo = ImageUploadField()
    description_fr = serializers.CharField(min_length=10, max_length=500)
    description_ar = serializers.CharField(min_length=10, max_length=500)
    address = serializers.CharField(min_length=5, max_length=255)
    phone = PhoneField()
    whatsapp = PhoneField()
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)
    owner_full_name = serializers.CharField(min_length=3, max_length=120)
    id_card_front = ImageUploadField()
    id_card_back = ImageUploadField()

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": [PASSWORDS_DIFFER]})
        _validate_new_password(attrs["password"], attrs["email"])
        return attrs

    def processed_files(self):
        """Traite les images apres validation : logo en WebP, cartes nettoyees."""
        data = self.validated_data
        return RegistrationFiles(
            logo=process_logo(data["logo"]),
            id_card_front=sanitize_private_image(data["id_card_front"]),
            id_card_back=sanitize_private_image(data["id_card_back"]),
        )

    def shop_fields(self) -> dict:
        data = self.validated_data
        return {
            "name": data["shop_name"].strip(),
            "description_fr": data["description_fr"].strip(),
            "description_ar": data["description_ar"].strip(),
            "address": data["address"].strip(),
            "phone": data["phone"],
            "whatsapp": data["whatsapp"],
            "owner_full_name": data["owner_full_name"].strip(),
        }


class EmailCodeSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    code = OtpCodeField()


class ResendOtpSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    purpose = serializers.ChoiceField(
        choices=[OtpCode.Purpose.REGISTRATION, OtpCode.Purpose.PASSWORD_RESET]
    )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(max_length=2048)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class ResetPasswordSerializer(serializers.Serializer):
    reset_token = serializers.CharField(max_length=512)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password_confirm = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": [PASSWORDS_DIFFER]})
        return attrs

    def validate_password_for(self, user: User) -> None:
        try:
            password_validation.validate_password(self.validated_data["new_password"], user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"new_password": list(error.messages)}) from None


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password_confirm = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate_current_password(self, value: str) -> str:
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError(_("Le mot de passe actuel est incorrect."))
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": [PASSWORDS_DIFFER]})
        try:
            password_validation.validate_password(
                attrs["new_password"], user=self.context["request"].user
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError({"new_password": list(error.messages)}) from None
        return attrs


class ChangeEmailRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField(max_length=254)
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate_current_password(self, value: str) -> str:
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError(_("Le mot de passe actuel est incorrect."))
        return value

    def validate_new_email(self, value: str) -> str:
        value = value.strip().lower()
        if value == self.context["request"].user.email:
            raise serializers.ValidationError(
                _("La nouvelle adresse doit être différente de l'adresse actuelle.")
            )
        return value


class ChangeEmailConfirmSerializer(serializers.Serializer):
    code = OtpCodeField()
