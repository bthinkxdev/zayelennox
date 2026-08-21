import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0015_rename_brand_to_zaye_lennox'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='mrp',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Required for simple products. Optional when the product has variants — each variant may carry its own MRP instead.', max_digits=12, null=True, verbose_name='MRP'),
        ),
        migrations.AlterField(
            model_name='product',
            name='purchase_price',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Required for simple products. Optional when the product has variants — each variant may carry its own purchase price instead.', max_digits=12, null=True, verbose_name='Purchase Price'),
        ),
        migrations.AlterField(
            model_name='product',
            name='weight_kg',
            field=models.DecimalField(blank=True, decimal_places=3, default=0.5, help_text='Weight in kilograms, used for courier booking. Required unless every variant below supplies its own weight override.', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Weight (kg)'),
        ),
        migrations.AlterField(
            model_name='product',
            name='length_cm',
            field=models.DecimalField(blank=True, decimal_places=2, default=10, help_text='Length in centimeters. Required unless every variant below supplies its own length override.', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Length (cm)'),
        ),
        migrations.AlterField(
            model_name='product',
            name='width_cm',
            field=models.DecimalField(blank=True, decimal_places=2, default=10, help_text='Width (breadth) in centimeters. Required unless every variant below supplies its own width override.', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Width (cm)'),
        ),
        migrations.AlterField(
            model_name='product',
            name='height_cm',
            field=models.DecimalField(blank=True, decimal_places=2, default=10, help_text='Height in centimeters. Required unless every variant below supplies its own height override.', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Height (cm)'),
        ),
        migrations.AlterField(
            model_name='productvariant',
            name='price_delta',
            field=models.DecimalField(decimal_places=2, default=0, help_text="Amount added to the product base price. Computed automatically from the variant's actual price entered in the dashboard — not vendor-editable directly.", max_digits=12, verbose_name='Price delta'),
        ),
        migrations.AddField(
            model_name='productvariant',
            name='mrp',
            field=models.DecimalField(blank=True, decimal_places=2, help_text="Leave blank to fall back to the product's MRP (offset by this variant's price difference).", max_digits=12, null=True, verbose_name='MRP override'),
        ),
        migrations.AddField(
            model_name='productvariant',
            name='purchase_price',
            field=models.DecimalField(blank=True, decimal_places=2, help_text="Leave blank to fall back to the product's purchase price (offset by this variant's price difference).", max_digits=12, null=True, verbose_name='Purchase price override'),
        ),
    ]
