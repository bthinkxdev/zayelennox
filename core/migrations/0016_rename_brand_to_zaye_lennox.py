from django.db import migrations, models


def rename_brand_to_zaye_lennox(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    SiteSettings.objects.filter(pk=1).update(site_name="ZAYE LENNOX")


def reverse_rename(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    SiteSettings.objects.filter(pk=1).update(site_name="DESERT STAR MOBILE PHONES")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_switch_default_currency_to_inr"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sitesettings",
            name="site_name",
            field=models.CharField(default="ZAYE LENNOX", max_length=120),
        ),
        migrations.RunPython(rename_brand_to_zaye_lennox, reverse_rename),
    ]
