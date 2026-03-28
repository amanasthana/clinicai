from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reception', '0002_visit_cancellation_reason_alter_visit_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='visit',
            name='consultation_fee',
            field=models.DecimalField(decimal_places=2, max_digits=8, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='visit',
            name='fee_receipt_number',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='visit',
            name='fee_paid_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='visit',
            name='payment_mode',
            field=models.CharField(
                blank=True, max_length=12,
                choices=[
                    ('cash', 'Cash'), ('upi', 'UPI'), ('card', 'Card'),
                    ('insurance', 'Insurance'), ('waived', 'Waived'),
                ],
            ),
        ),
    ]
