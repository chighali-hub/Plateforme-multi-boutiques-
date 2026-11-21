import factory
from django.utils import timezone

from apps.accounts.models import OtpCode, User

DEFAULT_PASSWORD = "Motdepasse!2026"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"boutique{n}@example.com")
    role = User.Role.SHOP
    is_email_verified = True
    password = DEFAULT_PASSWORD

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Passe par le manager : e-mail en minuscules et mot de passe hache.
        return model_class.objects.create_user(*args, **kwargs)


class AdminUserFactory(UserFactory):
    email = factory.Sequence(lambda n: f"admin{n}@example.com")
    role = User.Role.ADMIN


class OtpCodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OtpCode

    user = factory.SubFactory(UserFactory, is_email_verified=False)
    purpose = OtpCode.Purpose.REGISTRATION
    sent_to = factory.SelfAttribute("user.email")
    code_hash = "hash-de-test"
    expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(minutes=10))
