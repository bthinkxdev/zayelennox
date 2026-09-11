# Generated manually to add PayU payment gateway support alongside Razorpay.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_sitesettings_shiprocket_email_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="active_payment_gateway",
            field=models.CharField(
                choices=[("razorpay", "Razorpay"), ("payu", "PayU")],
                default="razorpay",
                help_text="Payment gateway customers pay through at checkout. Only this gateway's credentials are used — switching here does not affect the existing checkout or shipping flow.",
                max_length=20,
                verbose_name="Active Payment Gateway",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="payu_merchant_key",
            field=models.CharField(
                blank=True,
                help_text="PayU Merchant Key for payment processing.",
                max_length=120,
                verbose_name="PayU Merchant Key",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="payu_merchant_salt",
            field=models.CharField(
                blank=True,
                help_text="PayU Merchant Salt for payment hash verification.",
                max_length=120,
                verbose_name="PayU Merchant Salt",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="payu_test_mode",
            field=models.BooleanField(
                default=True,
                help_text="Use PayU's test/sandbox endpoint. Turn off only once you have live PayU credentials configured above.",
                verbose_name="PayU Test Mode",
            ),
        ),
    ]
