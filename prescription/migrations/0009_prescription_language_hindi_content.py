from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prescription', '0008_add_route_to_prescription_medicine'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE prescription_prescription ADD COLUMN IF NOT EXISTS language varchar(2) NOT NULL DEFAULT 'en';
                ALTER TABLE prescription_prescription ADD COLUMN IF NOT EXISTS hindi_content jsonb NULL;
            """,
            reverse_sql="""
                ALTER TABLE prescription_prescription DROP COLUMN IF EXISTS language;
                ALTER TABLE prescription_prescription DROP COLUMN IF EXISTS hindi_content;
            """,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='prescription',
                    name='language',
                    field=models.CharField(choices=[('en', 'English'), ('hi', 'Hindi')], default='en', max_length=2),
                ),
                migrations.AddField(
                    model_name='prescription',
                    name='hindi_content',
                    field=models.JSONField(blank=True, null=True),
                ),
            ],
            database_operations=[],
        ),
    ]
