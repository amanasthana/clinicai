from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prescription', '0006_add_drug_interactions'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE prescription_prescription
                            ADD COLUMN IF NOT EXISTS comorbidities TEXT NOT NULL DEFAULT '';
                        ALTER TABLE prescription_prescription
                            ADD COLUMN IF NOT EXISTS past_history TEXT NOT NULL DEFAULT '';
                        ALTER TABLE prescription_prescription
                            ADD COLUMN IF NOT EXISTS drug_allergies TEXT NOT NULL DEFAULT '';
                    """,
                    reverse_sql="""
                        ALTER TABLE prescription_prescription DROP COLUMN IF EXISTS comorbidities;
                        ALTER TABLE prescription_prescription DROP COLUMN IF EXISTS past_history;
                        ALTER TABLE prescription_prescription DROP COLUMN IF EXISTS drug_allergies;
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='prescription',
                    name='comorbidities',
                    field=models.TextField(blank=True, default=''),
                ),
                migrations.AddField(
                    model_name='prescription',
                    name='past_history',
                    field=models.TextField(blank=True, default=''),
                ),
                migrations.AddField(
                    model_name='prescription',
                    name='drug_allergies',
                    field=models.TextField(blank=True, default=''),
                ),
            ],
        ),
    ]
