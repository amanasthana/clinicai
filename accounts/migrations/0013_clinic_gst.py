from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_clinic_license_numbers'),
    ]

    operations = [
        migrations.AddField(
            model_name='clinic',
            name='gst_number',
            field=models.CharField(blank=True, default='', max_length=15),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='clinic',
            name='default_gst_percent',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]
