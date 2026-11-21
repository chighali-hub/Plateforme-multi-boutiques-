from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Verifie que l'API et la base de donnees repondent."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(tags=["Systeme"], summary="Etat de sante de l'API")
    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return Response({"status": "ok"})
