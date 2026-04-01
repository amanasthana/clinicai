from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0018_staffmember_access_expires_at'),
    ]

    operations = [
        # Using RunSQL with IF NOT EXISTS so this is safe to re-run if a previous
        # deploy was interrupted mid-migration (production deployment rule).
        migrations.RunSQL(
            sql="""
                ALTER TABLE accounts_staffmember
                ADD COLUMN IF NOT EXISTS phone VARCHAR(10) NOT NULL DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE accounts_staffmember
                DROP COLUMN IF EXISTS phone;
            """,
            state_operations=[
                migrations.AddField(
                    model_name='staffmember',
                    name='phone',
                    field=models.CharField(
                        blank=True,
                        help_text="Staff mobile number — used to build their login User ID.",
                        max_length=10,
                    ),
                ),
            ],
        ),
    ]
