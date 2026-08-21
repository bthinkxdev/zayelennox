from django.db import migrations


def update_zaye_lennox_contact_details(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    SiteSettings.objects.filter(pk=1).update(
        vendor_email="zayelennox@gmail.com",
        whatsapp_number="919292773339",
    )


def reverse_contact_details(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    SiteSettings.objects.filter(pk=1).update(
        vendor_email="desertmobiles@gmail.com",
        whatsapp_number="971503131065",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_rename_brand_to_zaye_lennox"),
    ]

    operations = [
        migrations.RunPython(update_zaye_lennox_contact_details, reverse_contact_details),
    ]
