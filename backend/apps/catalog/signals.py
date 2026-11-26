"""Signaux du catalogue. Voir 04-schema-base-de-donnees.md section 9.5.

Les fichiers image d'un produit supprime sont effaces apres la validation de la
transaction : une suppression annulee ne fait perdre aucun fichier.
"""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.core.storage import delete_file_on_commit

from .models import Product


@receiver(post_delete, sender=Product, dispatch_uid="catalog_product_delete_files")
def delete_product_files(sender, instance: Product, **kwargs) -> None:
    """Supprime l'image et la miniature d'un produit supprime.

    Couvre `instance.delete()` comme `QuerySet.delete()`. Une suppression deja
    demandee ailleurs (retrait par l'admin) est sans effet : le stockage ignore
    un fichier absent.
    """
    delete_file_on_commit(instance.image)
    delete_file_on_commit(instance.thumbnail)
