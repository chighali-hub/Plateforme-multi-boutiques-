import factory

from apps.accounts.tests.factories import AdminUserFactory
from apps.core.models import AuditAction, AuditLog


class AuditLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditLog

    actor = factory.SubFactory(AdminUserFactory)
    action = AuditAction.SHOP_APPROVED
    target_type = "shop"
    target_id = 1
