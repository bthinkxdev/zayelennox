import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0016_variant_first_pricing_and_optional_dims'),
    ]

    operations = [
        migrations.AddField(
            model_name='productimage',
            name='variant',
            field=models.ForeignKey(blank=True, help_text='Leave blank for a product-level image. Set to scope this image to one variant.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='images', to='catalog.productvariant', verbose_name='Variant'),
        ),
        migrations.AlterField(
            model_name='productimage',
            name='is_primary',
            field=models.BooleanField(db_index=True, default=False, help_text='Primary image shown on PLP cards and homepage rails. For a variant image, this is the one shown first in the PDP gallery when that variant is selected.', verbose_name='Is primary'),
        ),
        migrations.AddIndex(
            model_name='productimage',
            index=models.Index(fields=['variant', 'display_order'], name='cat_img_variant_order_idx'),
        ),
    ]
