"""Cree la ligne unique des parametres de la plateforme (id = 1)."""

from django.db import migrations


def create_row(apps, schema_editor):
    PlatformSettings = apps.get_model("core", "PlatformSettings")
    PlatformSettings.objects.get_or_create(pk=1)


def delete_row(apps, schema_editor):
    PlatformSettings = apps.get_model("core", "PlatformSettings")
    PlatformSettings.objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0002_platform_settings_audit_log")]

    operations = [migrations.RunPython(create_row, delete_row)]
