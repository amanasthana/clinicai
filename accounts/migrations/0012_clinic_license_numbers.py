from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0011_clinicdeletionrequest'),
    ]
    operations = [
        migrations.AddField(
            model_name='clinic',
            name='drug_license_number',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='clinic',
            name='medical_license_number',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
