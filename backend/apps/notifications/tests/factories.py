import factory

from apps.accounts.tests.factories import UserFactory
from apps.notifications.models import Notification, NotificationType


class NotificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Notification

    recipient = factory.SubFactory(UserFactory)
    type = NotificationType.SHOP_UNBLOCKED
    data = factory.LazyFunction(dict)
