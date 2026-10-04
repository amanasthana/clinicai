from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0022_hindi_rx_fields'),
    ]

    operations = [
        # Existing staff get TRUE (they already know the app); afterwards the default is FALSE
        # so only accounts created from now on see the first-login tour.
        # Both statements are idempotent — safe to re-run after a partial deploy.
        migrations.RunSQL(
            sql="""
                ALTER TABLE accounts_staffmember ADD COLUMN IF NOT EXISTS tour_completed boolean NOT NULL DEFAULT true;
                ALTER TABLE accounts_staffmember ALTER COLUMN tour_completed SET DEFAULT false;
            """,
            reverse_sql="ALTER TABLE accounts_staffmember DROP COLUMN IF EXISTS tour_completed;",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffmember',
                    name='tour_completed',
                    field=models.BooleanField(default=False),
                ),
            ],
            database_operations=[],
        ),
    ]
