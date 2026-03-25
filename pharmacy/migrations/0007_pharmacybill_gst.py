from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0006_dispenseditem_quantity_returned'),
    ]

    operations = [
        migrations.AddField(
            model_name='pharmacybill',
            name='gst_percent',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name='pharmacybill',
            name='gst_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
