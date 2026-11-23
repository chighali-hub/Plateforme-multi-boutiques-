"""Format des notifications. Voir 03-reference-api.md section 9.

Le titre et le message sont produits a la lecture, dans la langue de la requete.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Notification
from .services import render

IS_READ_INVALID = _("Valeur attendue : true ou false.")


class NotificationSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "type", "title", "message", "data", "is_read", "read_at", "created_at"]
        read_only_fields = fields

    def _texts(self, notification: Notification) -> tuple[str, str]:
        cache = self.context.setdefault("_texts", {})
        if notification.pk not in cache:
            cache[notification.pk] = render(notification)
        return cache[notification.pk]

    def get_title(self, notification: Notification) -> str:
        return self._texts(notification)[0]

    def get_message(self, notification: Notification) -> str:
        return self._texts(notification)[1]


class NotificationListQuerySerializer(serializers.Serializer):
    """Filtre facultatif `is_read=true|false` ; toute autre valeur est refusee."""

    is_read = serializers.ChoiceField(
        choices=["true", "false"],
        required=False,
        error_messages={"invalid_choice": IS_READ_INVALID},
    )


class UnreadCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class ReadAllSerializer(serializers.Serializer):
    updated_count = serializers.IntegerField()
