"""Vues des notifications (boutiques et administrateurs). Voir 03-reference-api.md section 9.

Un utilisateur ne voit et ne marque que ses propres notifications : une
notification d'un autre renvoie 404, jamais 403.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.openapi import error_responses
from apps.core.permissions import IsActiveAccount

from . import serializers, services
from .models import Notification

TAG = "Notifications"
ACCOUNT_ERRORS = ("401 AUTHENTICATION_REQUIRED", "403 SHOP_BLOCKED", "403 SHOP_EXPIRED")


def _own_notifications(request):
    return Notification.objects.filter(recipient=request.user)


class NotificationListView(ListAPIView):
    """Paginee, de la plus recente a la plus ancienne. Filtre `is_read`."""

    permission_classes = [IsActiveAccount]
    serializer_class = serializers.NotificationSerializer
    filter_backends: list = []

    def get_queryset(self):
        query = serializers.NotificationListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        queryset = _own_notifications(self.request).order_by("-created_at", "-id")
        is_read = query.validated_data.get("is_read")
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read == "true")
        return queryset

    @extend_schema(
        tags=[TAG],
        summary="Mes notifications",
        parameters=[
            OpenApiParameter("is_read", str, OpenApiParameter.QUERY, enum=["true", "false"])
        ],
        responses={
            200: serializers.NotificationSerializer(many=True),
            **error_responses("400 VALIDATION_ERROR", *ACCOUNT_ERRORS, "404 NOT_FOUND"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class UnreadCountView(APIView):
    permission_classes = [IsActiveAccount]

    @extend_schema(
        tags=[TAG],
        summary="Nombre de notifications non lues",
        responses={200: serializers.UnreadCountSerializer, **error_responses(*ACCOUNT_ERRORS)},
    )
    def get(self, request):
        count = _own_notifications(request).filter(is_read=False).count()
        return Response({"count": count})


class MarkReadView(APIView):
    permission_classes = [IsActiveAccount]

    @extend_schema(
        tags=[TAG],
        summary="Marquer une notification comme lue",
        request=None,
        responses={
            200: serializers.NotificationSerializer,
            **error_responses(*ACCOUNT_ERRORS, "404 NOT_FOUND"),
        },
    )
    def post(self, request, pk: int):
        notification = get_object_or_404(_own_notifications(request), pk=pk)
        notification = services.mark_as_read(notification)
        return Response(serializers.NotificationSerializer(notification).data)


class MarkAllReadView(APIView):
    permission_classes = [IsActiveAccount]

    @extend_schema(
        tags=[TAG],
        summary="Marquer toutes mes notifications comme lues",
        request=None,
        responses={200: serializers.ReadAllSerializer, **error_responses(*ACCOUNT_ERRORS)},
    )
    def post(self, request):
        return Response({"updated_count": services.mark_all_as_read(request.user)})
