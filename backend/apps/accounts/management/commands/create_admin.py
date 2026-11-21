"""Cree un administrateur de la plateforme.

    python manage.py create_admin --email admin@plateforme.mr

Le mot de passe est demande deux fois, saisie masquee : il n'apparait ni dans
l'historique du shell ni dans la liste des processus.
"""

from getpass import getpass

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from apps.accounts.models import User

MAX_PROMPTS = 3


class Command(BaseCommand):
    help = "Cree un administrateur de la plateforme (role ADMIN, e-mail verifie)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Adresse e-mail de l'administrateur.")

    def handle(self, *args, email: str, **options):
        email = email.strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError("Adresse e-mail invalide.") from None
        if User.objects.filter(email=email).exists():
            raise CommandError("Un compte utilise deja cette adresse e-mail.")

        password = self._ask_password(User(email=email, role=User.Role.ADMIN))
        User.objects.create_user(
            email=email, password=password, role=User.Role.ADMIN, is_email_verified=True
        )
        self.stdout.write(self.style.SUCCESS(f"Administrateur {email} cree."))

    def _ask_password(self, probe: User) -> str:
        for _attempt in range(MAX_PROMPTS):
            password = getpass("Mot de passe : ")
            if password != getpass("Confirmation : "):
                self.stderr.write("Les deux mots de passe ne correspondent pas.")
                continue
            try:
                password_validation.validate_password(password, user=probe)
            except ValidationError as error:
                for message in error.messages:
                    self.stderr.write(message)
                continue
            return password
        raise CommandError("Mot de passe refuse apres plusieurs essais.")
