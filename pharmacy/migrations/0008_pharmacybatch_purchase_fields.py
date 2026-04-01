from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0007_pharmacybill_gst'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE pharmacy_pharmacybatch "
                        "ADD COLUMN IF NOT EXISTS purchase_price DECIMAL(10,2) NOT NULL DEFAULT 0;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE pharmacy_pharmacybatch "
                        "DROP COLUMN IF EXISTS purchase_price;"
                    ),
                ),
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE pharmacy_pharmacybatch "
                        "ADD COLUMN IF NOT EXISTS purchase_gst_percent DECIMAL(5,2) NOT NULL DEFAULT 0;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE pharmacy_pharmacybatch "
                        "DROP COLUMN IF EXISTS purchase_gst_percent;"
                    ),
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='pharmacybatch',
                    name='purchase_price',
                    field=models.DecimalField(
                        decimal_places=2, default=0, max_digits=10,
                        help_text='Cost price per unit (excl. GST). Used for P&L calculation.'
                    ),
                ),
                migrations.AddField(
                    model_name='pharmacybatch',
                    name='purchase_gst_percent',
                    field=models.DecimalField(
                        decimal_places=2, default=0, max_digits=5,
                        help_text='GST % on purchase (e.g. 12 for 12%).'
                    ),
                ),
            ],
        ),
    ]
