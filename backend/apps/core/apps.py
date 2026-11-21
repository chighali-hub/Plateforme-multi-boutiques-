from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Socle commun"

    def ready(self) -> None:
        import mimetypes

        from django.conf import settings
        from PIL import Image

        # L'image Docker n'a pas /etc/mime.types : sans cela, .webp serait servi
        # en application/octet-stream (et refuse comme image avec nosniff).
        mimetypes.add_type("image/webp", ".webp")

        # Pillow refuse d'ouvrir une image plus grande : protection contre les
        # bombes de decompression (07-securite.md section 4).
        Image.MAX_IMAGE_PIXELS = settings.IMAGE_MAX_PIXELS
