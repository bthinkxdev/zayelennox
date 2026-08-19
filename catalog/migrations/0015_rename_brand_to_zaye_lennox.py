from django.db import migrations

OLD_BRAND = "Desert Star"
NEW_BRAND = "ZAYE LENNOX"


def rename_brand_in_seo_fields(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Product = apps.get_model("catalog", "Product")

    for category in Category.objects.filter(meta_title__icontains=OLD_BRAND):
        category.meta_title = category.meta_title.replace(OLD_BRAND, NEW_BRAND)
        category.save(update_fields=["meta_title"])

    for category in Category.objects.filter(meta_description__icontains=OLD_BRAND):
        category.meta_description = category.meta_description.replace(OLD_BRAND, NEW_BRAND)
        category.save(update_fields=["meta_description"])

    for product in Product.objects.filter(meta_title__icontains=OLD_BRAND):
        product.meta_title = product.meta_title.replace(OLD_BRAND, NEW_BRAND)
        product.save(update_fields=["meta_title"])

    for product in Product.objects.filter(meta_description__icontains=OLD_BRAND):
        product.meta_description = product.meta_description.replace(OLD_BRAND, NEW_BRAND)
        product.save(update_fields=["meta_description"])


def reverse_rename(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Product = apps.get_model("catalog", "Product")

    for category in Category.objects.filter(meta_title__icontains=NEW_BRAND):
        category.meta_title = category.meta_title.replace(NEW_BRAND, OLD_BRAND)
        category.save(update_fields=["meta_title"])

    for category in Category.objects.filter(meta_description__icontains=NEW_BRAND):
        category.meta_description = category.meta_description.replace(NEW_BRAND, OLD_BRAND)
        category.save(update_fields=["meta_description"])

    for product in Product.objects.filter(meta_title__icontains=NEW_BRAND):
        product.meta_title = product.meta_title.replace(NEW_BRAND, OLD_BRAND)
        product.save(update_fields=["meta_title"])

    for product in Product.objects.filter(meta_description__icontains=NEW_BRAND):
        product.meta_description = product.meta_description.replace(NEW_BRAND, OLD_BRAND)
        product.save(update_fields=["meta_description"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0014_alter_product_height_cm_alter_product_length_cm_and_more"),
    ]

    operations = [
        migrations.RunPython(rename_brand_in_seo_fields, reverse_rename),
    ]
