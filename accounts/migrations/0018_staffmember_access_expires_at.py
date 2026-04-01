from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0017_alter_clinicaiexecutive_id_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE accounts_staffmember "
                        "ADD COLUMN IF NOT EXISTS access_expires_at TIMESTAMPTZ NULL;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE accounts_staffmember "
                        "DROP COLUMN IF EXISTS access_expires_at;"
                    ),
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='staffmember',
                    name='access_expires_at',
                    field=models.DateTimeField(
                        blank=True, null=True,
                        help_text='If set, staff cannot log in after this date/time.'
                    ),
                ),
            ],
        ),
    ]
