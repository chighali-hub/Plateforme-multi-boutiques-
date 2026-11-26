"""Serializers du catalogue de l'espace boutique.

Voir 03-reference-api.md section 6. Les champs sont listes explicitement :
`shop` n'est jamais lu depuis la requete (07-securite.md section 3).
"""

from rest_framework import serializers

from .models import Category

CATEGORY_NAME_MAX_LENGTH = 60
# Ordre d'affichage : positif, dans la plage d'un smallint PostgreSQL.
SORT_ORDER_MIN = 0
SORT_ORDER_MAX = 32767


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
