import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0009_pharmacybill_discount_amount'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='pharmacybatch',
            options={'base_manager_name': 'all_objects', 'ordering': ['expiry_date']},
        ),
        migrations.AlterModelOptions(
            name='pharmacyitem',
            options={'base_manager_name': 'all_objects'},
        ),
        migrations.AlterModelManagers(
            name='pharmacybatch',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='pharmacyitem',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddField(
            model_name='pharmacybatch',
            name='is_archived',
            field=models.BooleanField(db_default=False, db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='pharmacyitem',
            name='is_archived',
            field=models.BooleanField(db_default=False, db_index=True, default=False),
        ),
    ]
