"""Vues de l'espace boutique : designs, onboarding, profil, banques, recharge.

Voir 03-reference-api.md section 5. Les etats autorises reprennent exactement
la matrice de la section 0.3 ; les vues partent toujours de `request.shop`.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.models import Recharge
from apps.core.models import PlatformSettings
from apps.core.openapi import error_responses
from apps.core.permissions import IsShopOwner, ShopStateAllowed, admin_contact_details
from apps.core.storage import private_file_response

from . import serializers, services
from .models import BankAccount, ShopState, ThemeTemplate

TAG_THEMES = "Public - Designs"
TAG_ONBOARDING = "Boutique - Onboarding"
TAG_PROFILE = "Boutique - Profil"
TAG_BANKS = "Boutique - Banques"
TAG_RECHARGE = "Boutique - Recharge"

ONBOARDING = ShopState.ONBOARDING
PENDING = ShopState.PENDING
REJECTED = ShopState.REJECTED
ACTIVE = ShopState.ACTIVE

SHOP_ERRORS = ("401 AUTHENTICATION_REQUIRED", "403 SHOP_BLOCKED", "403 SHOP_EXPIRED")
STATE_ERRORS = (*SHOP_ERRORS, "403 SHOP_STATE_FORBIDDEN")
ID_CARD_FIELDS = {"front": "id_card_front", "back": "id_card_back"}


def _profile_response(request, shop, http_status=status.HTTP_200_OK) -> Response:
    data = serializers.ShopProfileSerializer(shop, context={"request": request}).data
    return Response(data, status=http_status)


# --- Designs (public) -------------------------------------------------------------
class ThemeListView(ListAPIView):
    """Galerie des designs : modeles actifs tries par sort_order, non paginee."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    pagination_class = None
    filter_backends: list = []
    serializer_class = serializers.ThemeSerializer
    queryset = ThemeTemplate.objects.filter(is_active=True).order_by("sort_order", "id")

    @extend_schema(tags=[TAG_THEMES], summary="Galerie des designs")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# --- Onboarding (RG-05) -----------------------------------------------------------
class OnboardingDesignView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ONBOARDING)]

    @extend_schema(
        tags=[TAG_ONBOARDING],
        summary="Choisir le design pendant l'inscription",
        request=serializers.DesignSerializer,
        responses={
            200: serializers.ShopProfileSerializer,
            **error_responses(
                "400 VALIDATION_ERROR", *STATE_ERRORS, "409 ONBOARDING_STEP_MISMATCH"
            ),
        },
    )
    def post(self, request):
        serializer = serializers.DesignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = services.choose_design(request.shop, **serializer.validated_data)
        return _profile_response(request, shop)


class OnboardingAcceptTermsView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ONBOARDING)]

    @extend_schema(
        tags=[TAG_ONBOARDING],
        summary="Accepter les conditions et soumettre la demande",
        request=serializers.AcceptTermsSerializer,
        responses={
            200: serializers.ShopProfileSerializer,
            **error_responses(
                "400 VALIDATION_ERROR", *STATE_ERRORS, "409 ONBOARDING_STEP_MISMATCH"
            ),
        },
    )
    def post(self, request):
        serializers.AcceptTermsSerializer(data=request.data).is_valid(raise_exception=True)
        shop = services.accept_terms(request.shop, request=request)
        return _profile_response(request, shop)


# --- Profil -----------------------------------------------------------------------
class ShopMeView(APIView):
    """GET : tous les etats. PATCH : REJECTED et ACTIVE."""

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsShopOwner(), ShopStateAllowed(REJECTED, ACTIVE)]
        return [IsShopOwner()]

    @extend_schema(
        tags=[TAG_PROFILE],
        summary="Profil de ma boutique",
        responses={200: serializers.ShopProfileSerializer, **error_responses(*SHOP_ERRORS)},
    )
    def get(self, request):
        return _profile_response(request, request.shop)

    @extend_schema(
        tags=[TAG_PROFILE],
        summary="Modifier le profil",
        request={"multipart/form-data": serializers.ShopProfileUpdateSerializer},
        responses={
            200: serializers.ShopProfileSerializer,
            **error_responses("400 VALIDATION_ERROR", *STATE_ERRORS, "413 FILE_TOO_LARGE"),
        },
    )
    def patch(self, request):
        serializer = serializers.ShopProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = services.update_profile(
            request.shop, fields=serializer.profile_fields(), logo=serializer.processed_logo()
        )
        return _profile_response(request, shop)


class ShopDesignView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(REJECTED, ACTIVE)]

    @extend_schema(
        tags=[TAG_PROFILE],
        summary="Changer le design",
        request=serializers.DesignSerializer,
        responses={
            200: serializers.ShopProfileSerializer,
            **error_responses("400 VALIDATION_ERROR", *STATE_ERRORS),
        },
    )
    def patch(self, request):
        serializer = serializers.DesignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = services.update_design(request.shop, **serializer.validated_data)
        return _profile_response(request, shop)


class IdCardUpdateView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(REJECTED)]

    @extend_schema(
        tags=[TAG_PROFILE],
        summary="Remplacer la carte d'identite",
        request={"multipart/form-data": serializers.IdCardSerializer},
        responses={
            200: serializers.ShopProfileSerializer,
            **error_responses("400 VALIDATION_ERROR", *STATE_ERRORS, "413 FILE_TOO_LARGE"),
        },
    )
    def put(self, request):
        serializer = serializers.IdCardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shop = services.replace_id_card(request.shop, **serializer.processed_files())
        return _profile_response(request, shop)


class IdCardFileView(APIView):
    """Fichier prive de la carte d'identite : jamais d'URL /media/."""

    permission_classes = [IsShopOwner, ShopStateAllowed(PENDING, REJECTED, ACTIVE)]

    @extend_schema(
        tags=[TAG_PROFILE],
        summary="Lire une face de ma carte d'identite",
        parameters=[OpenApiParameter("side", str, OpenApiParameter.PATH, enum=["front", "back"])],
        responses={
            (200, "image/*"): OpenApiTypes.BINARY,
            **error_responses(*STATE_ERRORS, "404 NOT_FOUND"),
        },
    )
    def get(self, request, side: str):
        field_name = ID_CARD_FIELDS.get(side)
        if field_name is None:
            raise NotFound()
        field_file = getattr(request.shop, field_name)
        if not field_file or not field_file.storage.exists(field_file.name):
            raise NotFound()
        return private_file_response(field_file)


class ResubmitView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(REJECTED)]

    @extend_schema(
        tags=[TAG_PROFILE],
        summary="Renvoyer la demande de validation",
        request=None,
        responses={
            200: serializers.ShopProfileSerializer,
            **error_responses(*STATE_ERRORS, "409 INVALID_STATE_TRANSITION"),
        },
    )
    def post(self, request):
        shop = services.resubmit_shop(request.shop, request=request)
        return _profile_response(request, shop)


# --- Banques ----------------------------------------------------------------------
class BankListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsShopOwner(), ShopStateAllowed(PENDING, REJECTED, ACTIVE)]
        return [IsShopOwner(), ShopStateAllowed(REJECTED, ACTIVE)]

    @extend_schema(
        tags=[TAG_BANKS],
        summary="Mes banques",
        responses={
            200: serializers.BankAccountSerializer(many=True),
            **error_responses(*STATE_ERRORS),
        },
    )
    def get(self, request):
        banks = BankAccount.objects.filter(shop=request.shop).order_by("id")
        return Response(serializers.BankAccountSerializer(banks, many=True).data)

    @extend_schema(
        tags=[TAG_BANKS],
        summary="Ajouter une banque",
        request=serializers.BankAccountSerializer,
        responses={
            201: serializers.BankAccountSerializer,
            **error_responses("400 VALIDATION_ERROR", *STATE_ERRORS, "409 LIMIT_REACHED"),
        },
    )
    def post(self, request):
        serializer = serializers.BankAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = services.create_bank_account(request.shop, **serializer.validated_data)
        return Response(
            serializers.BankAccountSerializer(bank).data, status=status.HTTP_201_CREATED
        )


class BankDetailView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(REJECTED, ACTIVE)]

    def _get_bank(self, request, pk: int) -> BankAccount:
        """Une banque d'une autre boutique renvoie 404, jamais 403."""
        return get_object_or_404(BankAccount, pk=pk, shop=request.shop)

    @extend_schema(
        tags=[TAG_BANKS],
        summary="Modifier une banque",
        request=serializers.BankAccountSerializer(partial=True),
        responses={
            200: serializers.BankAccountSerializer,
            **error_responses("400 VALIDATION_ERROR", *STATE_ERRORS, "404 NOT_FOUND"),
        },
    )
    def patch(self, request, pk: int):
        bank = self._get_bank(request, pk)
        serializer = serializers.BankAccountSerializer(bank, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        bank = services.update_bank_account(bank, fields=serializer.validated_data)
        return Response(serializers.BankAccountSerializer(bank).data)

    @extend_schema(
        tags=[TAG_BANKS],
        summary="Supprimer une banque",
        responses={204: None, **error_responses(*STATE_ERRORS, "404 NOT_FOUND")},
    )
    def delete(self, request, pk: int):
        services.delete_bank_account(self._get_bank(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Recharge ---------------------------------------------------------------------
class RechargeInfoView(APIView):
    permission_classes = [IsShopOwner, ShopStateAllowed(ACTIVE)]

    @extend_schema(
        tags=[TAG_RECHARGE],
        summary="Informations pour recharger mon compte",
        responses={200: serializers.RechargeInfoSerializer, **error_responses(*STATE_ERRORS)},
    )
    def get(self, request):
        shop = request.shop
        contact = admin_contact_details(shop)
        data = {
            "expires_at": shop.expires_at,
            "days_left": shop.days_left() if shop.expires_at else None,
            "admin_whatsapp": contact["admin_whatsapp"],
            "whatsapp_url": contact["whatsapp_url"],
            "admin_contact_email": PlatformSettings.load().admin_contact_email,
        }
        return Response(serializers.RechargeInfoSerializer(data).data)


class ShopRechargeListView(ListAPIView):
    """Historique des recharges de la boutique, du plus recent au plus ancien."""

    permission_classes = [IsShopOwner, ShopStateAllowed(ACTIVE)]
    serializer_class = serializers.ShopRechargeSerializer
    filter_backends: list = []

    def get_queryset(self):
        return Recharge.objects.filter(shop=self.request.shop).order_by("-created_at", "-id")

    @extend_schema(
        tags=[TAG_RECHARGE],
        summary="Historique de mes recharges",
        responses={
            200: serializers.ShopRechargeSerializer(many=True),
            **error_responses(*STATE_ERRORS, "404 NOT_FOUND"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
