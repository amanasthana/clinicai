from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reception', '0004_alter_patient_age'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE reception_patient ADD COLUMN IF NOT EXISTS guardian_name VARCHAR(150) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE reception_patient DROP COLUMN IF EXISTS guardian_name;",
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='patient',
                    name='guardian_name',
                    field=models.CharField(blank=True, help_text="Husband's / Father's name (optional)", max_length=150),
                ),
            ],
        ),
    ]
