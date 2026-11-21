"""Active les extensions PostgreSQL utilisees par la recherche.

- pg_trgm       : index GIN trigrammes (recherche de sous-chaines rapide)
- unaccent      : suppression des accents
- fuzzystrmatch : distance de Levenshtein (tolerance aux fautes de frappe)
"""
from django.contrib.postgres.operations import (
    CreateExtension,
    TrigramExtension,
    UnaccentExtension,
)
from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies: list = []
    operations = [
        TrigramExtension(),
        UnaccentExtension(),
        CreateExtension("fuzzystrmatch"),
    ]
