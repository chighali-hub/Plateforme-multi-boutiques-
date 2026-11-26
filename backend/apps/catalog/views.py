"""Vues du catalogue de l'espace boutique : categories.

Voir 03-reference-api.md section 6. Tous ces endpoints exigent l'etat ACTIVE
(matrice de la section 0.3) et partent toujours de `request.shop`.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.openapi import error_responses
from apps.core.permissions import IsShopOwner, ShopStateAllowed
from apps.shops.models import ShopState

from . import selectors, serializers, services
from .models import Category

TAG_CATEGORIES = "Boutique - Catégories"

SHOP_ERRORS = (
    "401 AUTHENTICATION_REQUIRED",
    "403 PERMISSION_DENIED",
    "403 SHOP_BLOCKED",
    "403 SHOP_EXPIRED",
    "403 SHOP_STATE_FORBIDDEN",
)


def _get_category(request, pk: int) -> Category:
    """Categorie de la boutique connectee, avec `products_count`.

    Une categorie d'une autre boutique renvoie 404, jamais 403.
    """
    return get_object_or_404(selectors.get_shop_categories(request.shop), pk=pk)


class CategoryListCreateView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ShopState.ACTIVE)]

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Mes catégories",
        description="Liste non paginée, triée par `sort_order`, puis `name_fr`.",
        responses={
            200: serializers.CategorySerializer(many=True),
            **error_responses(*SHOP_ERRORS),
        },
    )
    def get(self, request):
        categories = selectors.get_shop_categories(request.shop)
        return Response(serializers.CategorySerializer(categories, many=True).data)

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Ajouter une catégorie",
        request=serializers.CategorySerializer,
        responses={
            201: serializers.CategorySerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "409 LIMIT_REACHED"),
        },
    )
    def post(self, request):
        serializer = serializers.CategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.create_category(request.shop, serializer.validated_data)
        return Response(
            serializers.CategorySerializer(_get_category(request, category.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class CategoryDetailView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ShopState.ACTIVE)]

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Modifier une catégorie",
        request=serializers.CategorySerializer(partial=True),
        responses={
            200: serializers.CategorySerializer,
            **error_responses("400 VALIDATION_ERROR", *SHOP_ERRORS, "404 NOT_FOUND"),
        },
    )
    def patch(self, request, pk: int):
        category = _get_category(request, pk)
        serializer = serializers.CategorySerializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_category(category, serializer.validated_data)
        return Response(serializers.CategorySerializer(_get_category(request, pk)).data)

    @extend_schema(
        tags=[TAG_CATEGORIES],
        summary="Supprimer une catégorie",
        description="Les produits de la catégorie deviennent sans catégorie (RG-32).",
        responses={204: None, **error_responses(*SHOP_ERRORS, "404 NOT_FOUND")},
    )
    def delete(self, request, pk: int):
        services.delete_category(_get_category(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)
