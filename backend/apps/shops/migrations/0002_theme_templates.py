"""Cree les 6 modeles de design et copie leurs apercus dans le stockage public.

Les apercus sources sont versionnes dans apps/shops/theme_previews/. Les
definitions sont figees ici (une migration ne depend pas du code courant).
"""

from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import migrations

PREVIEWS_DIR = Path(__file__).resolve().parent.parent / "theme_previews"

THEMES = [
    # code, name_fr, name_ar, layout, primary, accent
    ("classique", "Classique", "كلاسيكي", "GRID", "#064E3B", "#D4A52A"),
    ("elegant", "Élégant", "أنيق", "MAGAZINE", "#7C2D5B", "#D4A52A"),
    ("moderne", "Moderne", "عصري", "GRID", "#1E3A8A", "#F97316"),
    ("minimal", "Minimal", "بسيط", "MINIMAL", "#111827", "#6B7280"),
    ("magazine", "Magazine", "مجلة", "MAGAZINE", "#7F1D1D", "#F59E0B"),
    ("tradition", "Tradition", "تقليدي", "LIST", "#78350F", "#0E7490"),
]


def create_themes(apps, schema_editor):
    ThemeTemplate = apps.get_model("shops", "ThemeTemplate")
    for sort_order, (code, name_fr, name_ar, layout, primary, accent) in enumerate(THEMES, 1):
        preview_path = f"themes/{code}.webp"
        if not default_storage.exists(preview_path):
            content = (PREVIEWS_DIR / f"{code}.webp").read_bytes()
            preview_path = default_storage.save(preview_path, ContentFile(content))
        ThemeTemplate.objects.update_or_create(
            code=code,
            defaults={
                "name_fr": name_fr,
                "name_ar": name_ar,
                "layout": layout,
                "preview_image": preview_path,
                "default_primary_color": primary,
                "default_accent_color": accent,
                "is_active": True,
                "sort_order": sort_order,
            },
        )


def delete_themes(apps, schema_editor):
    ThemeTemplate = apps.get_model("shops", "ThemeTemplate")
    ThemeTemplate.objects.filter(code__in=[theme[0] for theme in THEMES]).delete()


class Migration(migrations.Migration):
    dependencies = [("shops", "0001_initial")]

    operations = [migrations.RunPython(create_themes, delete_themes)]
