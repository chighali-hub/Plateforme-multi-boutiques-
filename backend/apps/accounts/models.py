"""Modele utilisateur personnalise.

Il existe deux roles : ADMIN (administrateur de la plateforme) et SHOP (proprietaire
d'une boutique). Les clients n'ont pas de compte. La connexion se fait par e-mail.
Voir docs/Documentation-API/04-schema-base-de-donnees.md (table accounts_user).
"""

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.SHOP)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_email_verified", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", _("Administrateur")
        SHOP = "SHOP", _("Boutique")

    email = models.EmailField(_("e-mail"), unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.SHOP)
    is_email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "accounts_user"
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        constraints = [
            # RG-02 : l'e-mail est stocke en minuscules, l'unicite est donc
            # insensible a la casse.
            models.CheckConstraint(
                condition=Q(email=Lower("email")), name="accounts_user_email_lowercase"
            ),
            models.CheckConstraint(
                condition=Q(role__in=["ADMIN", "SHOP"]), name="accounts_user_role_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_shop(self) -> bool:
        return self.role == self.Role.SHOP


class OtpCode(models.Model):
    """Code a usage unique envoye par e-mail. Seul son hachage est stocke.

    Un code est valide si consumed_at est vide, expires_at dans le futur et
    attempts inferieur au maximum (voir 04-schema-base-de-donnees.md 2.2).
    """

    class Purpose(models.TextChoices):
        REGISTRATION = "REGISTRATION", _("Inscription")
        PASSWORD_RESET = "PASSWORD_RESET", _("Réinitialisation du mot de passe")
        EMAIL_CHANGE = "EMAIL_CHANGE", _("Changement d'e-mail")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="otp_codes"
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    sent_to = models.EmailField(max_length=254)
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_otp_code"
        verbose_name = _("code à usage unique")
        verbose_name_plural = _("codes à usage unique")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "purpose", "-created_at"], name="accounts_otp_lookup_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(purpose__in=["REGISTRATION", "PASSWORD_RESET", "EMAIL_CHANGE"]),
                name="accounts_otp_purpose_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.purpose} -> {self.user_id}"
