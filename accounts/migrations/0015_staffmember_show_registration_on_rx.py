from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_clinic_default_opd_fee'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE accounts_staffmember
                ADD COLUMN IF NOT EXISTS show_registration_on_rx BOOLEAN NOT NULL DEFAULT TRUE;
            """,
            reverse_sql="""
                ALTER TABLE accounts_staffmember
                DROP COLUMN IF EXISTS show_registration_on_rx;
            """,
            state_operations=[
                migrations.AddField(
                    model_name='staffmember',
                    name='show_registration_on_rx',
                    field=models.BooleanField(
                        default=True,
                        help_text='Print registration/licence number on prescriptions.'
                    ),
                ),
            ],
        ),
    ]
