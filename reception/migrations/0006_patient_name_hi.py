from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reception', '0005_add_guardian_name_to_patient'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE reception_patient ADD COLUMN IF NOT EXISTS name_hi varchar(200) NOT NULL DEFAULT '';",
            reverse_sql="ALTER TABLE reception_patient DROP COLUMN IF EXISTS name_hi;",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='patient',
                    name='name_hi',
                    field=models.CharField(blank=True, default='', max_length=200),
                ),
            ],
            database_operations=[],
        ),
    ]
