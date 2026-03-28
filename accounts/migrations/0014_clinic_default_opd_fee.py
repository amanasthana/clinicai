from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_clinic_gst'),
    ]

    operations = [
        migrations.AddField(
            model_name='clinic',
            name='default_opd_fee',
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=8,
                help_text='Default OPD consultation fee pre-filled when collecting fees (0 = no default).'
            ),
        ),
    ]
