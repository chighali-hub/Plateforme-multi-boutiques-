from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.tests.factories import AdminUserFactory
from apps.administration.models import Recharge
from apps.shops.tests.factories import ShopFactory


class RechargeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Recharge

    shop = factory.SubFactory(ShopFactory, active=True)
    performed_by = factory.SubFactory(AdminUserFactory)
    duration_months = 1
    previous_expires_at = factory.LazyFunction(timezone.now)
    new_expires_at = factory.LazyAttribute(lambda r: r.previous_expires_at + timedelta(days=30))
