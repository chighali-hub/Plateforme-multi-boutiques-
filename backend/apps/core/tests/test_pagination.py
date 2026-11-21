import pytest
from django.urls import path
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.core.pagination import PublicPagination, StandardPagination


class _UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id"]


class _ListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = _UserSerializer
    queryset = User.objects.order_by("id")


urlpatterns = [path("t/list/", _ListView.as_view())]

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]


def test_default_page_size_is_20(api_client):
    UserFactory.create_batch(25)
    body = api_client.get("/t/list/").json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 25 and len(body["results"]) == 20


def test_page_size_is_capped_at_100():
    assert StandardPagination.max_page_size == 100
    assert PublicPagination.page_size == 24


def test_page_size_parameter(api_client):
    UserFactory.create_batch(5)
    assert len(api_client.get("/t/list/?page_size=2").json()["results"]) == 2


def test_out_of_range_page_returns_not_found(api_client):
    UserFactory.create_batch(2)
    response = api_client.get("/t/list/?page=9")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
