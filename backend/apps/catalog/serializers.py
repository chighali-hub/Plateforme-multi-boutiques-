"""Serializers du catalogue de l'espace boutique.

Voir 03-reference-api.md section 6. Les champs sont listes explicitement :
`shop` n'est jamais lu depuis la requete (07-securite.md section 3).
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import ImageUploadField

from .models import PRODUCT_PRICE_MAX, PRODUCT_PRICE_MIN, Category, Product
from .services import PRODUCT_CATEGORY_UNKNOWN

CATEGORY_NAME_MAX_LENGTH = 60
# Ordre d'affichage : positif, dans la plage d'un smallint PostgreSQL.
SORT_ORDER_MIN = 0
SORT_ORDER_MAX = 32767
PRODUCT_NAME_MAX_LENGTH = 150
PRODUCT_DESCRIPTION_MAX_LENGTH = 2000


def _absolute(request, url: str) -> str:
    return request.build_absolute_uri(url) if request else url


class CategorySerializer(serializers.ModelSerializer):
    """Objet `Category` en sortie, et corps de POST / PATCH en entree.

    La regle « au moins un nom » et l'unicite sont controlees par le service,
    sur l'etat final de la categorie.
    """

    name_fr = serializers.CharField(
        max_length=CATEGORY_NAME_MAX_LENGTH, required=False, allow_blank=True
    )
    name_ar = serializers.CharField(
        max_length=CATEGORY_NAME_MAX_LENGTH, required=False, allow_blank=True
    )
    sort_order = serializers.IntegerField(
        required=False, min_value=SORT_ORDER_MIN, max_value=SORT_ORDER_MAX
    )
    products_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name_fr", "name_ar", "sort_order", "products_count", "created_at"]
        read_only_fields = ["id", "products_count", "created_at"]
        # L'unicite insensible a la casse est controlee par le service, dans la boutique.
        validators: list = []


# --- Produits ---------------------------------------------------------------------
class CategorySummarySerializer(serializers.ModelSerializer):
    """Categorie resumee dans l'objet `Product`."""

    class Meta:
        model = Category
        fields = ["id", "name_fr", "name_ar"]
        read_only_fields = fields


class ProductSerializer(serializers.ModelSerializer):
    """Objet `Product` de l'espace boutique (sortie uniquement)."""

    category = CategorySummarySerializer(read_only=True, allow_null=True)
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

    @extend_schema_field(OpenApiTypes.URI)
    def get_image_url(self, product: Product) -> str:
        return _absolute(self.context.get("request"), product.image.url)

    @extend_schema_field(OpenApiTypes.URI)
    def get_thumbnail_url(self, product: Product) -> str:
        return _absolute(self.context.get("request"), product.thumbnail.url)


class OptionalBooleanField(serializers.BooleanField):
    """Booleen facultatif, y compris en multipart.

    Par defaut, DRF lit un booleen absent d'un formulaire multipart comme `false`
    (case a cocher non cochee) : `is_available` omis passerait a `false` au lieu
    de garder sa valeur par defaut (`true`).
    """

    default_empty_html = serializers.empty


class ProductWriteSerializer(serializers.Serializer):
    """Corps de POST (multipart) et de PATCH (multipart, ou JSON sans image).

    Seuls ces champs sont lus : `shop`, `source`, `import_job`, `published_at`...
    sont ignores. `category_id` est cherche dans la boutique passee en contexte
    (`context["shop"]`) ; la regle « au moins un nom » est controlee par le
    service, sur l'etat final du produit.
    """

    name_fr = serializers.CharField(
        max_length=PRODUCT_NAME_MAX_LENGTH, required=False, allow_blank=True
    )
    name_ar = serializers.CharField(
        max_length=PRODUCT_NAME_MAX_LENGTH, required=False, allow_blank=True
    )
    description_fr = serializers.CharField(
        max_length=PRODUCT_DESCRIPTION_MAX_LENGTH, required=False, allow_blank=True
    )
    description_ar = serializers.CharField(
        max_length=PRODUCT_DESCRIPTION_MAX_LENGTH, required=False, allow_blank=True
    )
    price = serializers.IntegerField(min_value=PRODUCT_PRICE_MIN, max_value=PRODUCT_PRICE_MAX)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    image = ImageUploadField()
    status = serializers.ChoiceField(choices=Product.Status.choices, required=False)
    is_available = OptionalBooleanField(required=False)

    def validate_category_id(self, value: int | None) -> Category | None:
        """Categorie de la boutique ; inexistante ou d'une autre boutique : meme erreur."""
        if value is None:
            return None
        category = Category.objects.filter(shop=self.context["shop"], pk=value).first()
        if category is None:
            raise serializers.ValidationError(PRODUCT_CATEGORY_UNKNOWN)
        return category

    def validate(self, attrs: dict) -> dict:
        if "category_id" in attrs:
            attrs["category"] = attrs.pop("category_id")
        return attrs

    def product_fields(self) -> dict:
        """Champs du produit, sans le fichier image."""
        return {name: value for name, value in self.validated_data.items() if name != "image"}
