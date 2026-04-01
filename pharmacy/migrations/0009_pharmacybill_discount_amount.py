from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0008_pharmacybatch_purchase_fields'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE pharmacy_pharmacybill "
                        "ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(10,2) NOT NULL DEFAULT 0;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE pharmacy_pharmacybill "
                        "DROP COLUMN IF EXISTS discount_amount;"
                    ),
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='pharmacybill',
                    name='discount_amount',
                    field=models.DecimalField(
                        decimal_places=2, default=0, max_digits=10,
                        help_text='Flat ₹ discount. If > 0 this overrides discount_percent.'
                    ),
                ),
            ],
        ),
    ]
