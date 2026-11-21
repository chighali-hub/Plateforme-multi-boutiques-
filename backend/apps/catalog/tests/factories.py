import factory

from apps.catalog.models import Category, ImportErrorRow, ImportJob, Product
from apps.shops.tests.factories import ShopFactory


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    shop = factory.SubFactory(ShopFactory, active=True)
    name_fr = factory.Sequence(lambda n: f"Categorie {n}")
    name_ar = factory.Sequence(lambda n: f"فئة {n}")


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    shop = factory.SubFactory(ShopFactory, active=True)
    name_fr = factory.Sequence(lambda n: f"Melhfa {n}")
    name_ar = factory.Sequence(lambda n: f"ملحفة {n}")
    description_fr = "Voile en coton"
    price = 2500
    image = "products/2026/01/image.webp"
    thumbnail = "products/2026/01/thumb.webp"
    status = Product.Status.PUBLISHED
    is_available = True


class ImportJobFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImportJob

    shop = factory.SubFactory(ShopFactory, active=True)
    excel_file = "imports/2026/01/produits.xlsx"
    zip_file = "imports/2026/01/photos.zip"


class ImportErrorRowFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImportErrorRow

    job = factory.SubFactory(ImportJobFactory)
    shop = factory.SelfAttribute("job.shop")
    row_number = factory.Sequence(lambda n: n + 2)
    name_fr = "Produit sans prix"
    price_raw = "deux mille"
    errors = factory.LazyFunction(
        lambda: [{"field": "price", "code": "INVALID_PRICE", "message": "Prix invalide."}]
    )
