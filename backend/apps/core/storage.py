"""Stockage des fichiers. Voir 05-aspects-transversaux.md section 8.

Deux espaces : public (MEDIA_ROOT, servi par le serveur web) et prive
(PRIVATE_MEDIA_ROOT, sans URL, lu uniquement par des vues authentifiees).
"""

import mimetypes
import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from django.utils.deconstruct import deconstructible

ALLOWED_UPLOAD_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "xlsx", "zip"})


class PrivateMediaStorage(FileSystemStorage):
    """Stockage hors de MEDIA_ROOT, sans URL publique.

    L'emplacement est relu a chaque acces (pas de cache) : la valeur de
    PRIVATE_MEDIA_ROOT au moment de l'appel fait foi, y compris en test.
    """

    @property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Un fichier prive n'a pas d'URL : passer par une vue authentifiee.")


def private_storage() -> PrivateMediaStorage:
    """Appelable passe aux FileField prives (lu a l'execution, pas a l'import)."""
    return PrivateMediaStorage()


@deconstructible
class UploadTo:
    """Chemin `<prefixe>/AAAA/MM/<uuid4>.<ext>`.

    Le nom fourni par l'utilisateur n'est jamais conserve ; seule son extension
    est reprise si elle figure dans la liste autorisee.
    """

    def __init__(self, prefix: str):
        self.prefix = prefix.strip("/")

    def __call__(self, instance, filename: str) -> str:
        extension = os.path.splitext(filename or "")[1].lower().lstrip(".")
        suffix = f".{extension}" if extension in ALLOWED_UPLOAD_EXTENSIONS else ""
        now = timezone.now()
        return f"{self.prefix}/{now:%Y}/{now:%m}/{uuid.uuid4().hex}{suffix}"

    def __eq__(self, other) -> bool:
        return isinstance(other, UploadTo) and other.prefix == self.prefix

    def __hash__(self) -> int:
        return hash(self.prefix)


def private_file_response(field_file) -> FileResponse:
    """Sert un fichier prive a un utilisateur deja autorise par la vue."""
    content_type = mimetypes.guess_type(field_file.name)[0] or "application/octet-stream"
    response = FileResponse(field_file.open("rb"), content_type=content_type)
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def delete_file_on_commit(field_file) -> None:
    """Supprime un fichier apres la validation de la transaction en cours."""
    if not field_file:
        return
    storage, name = field_file.storage, field_file.name
    transaction.on_commit(lambda: storage.delete(name))
