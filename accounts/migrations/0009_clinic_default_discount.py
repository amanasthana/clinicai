from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0008_staffmember_must_change_password_passwordresetrequest'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE accounts_clinic ADD COLUMN IF NOT EXISTS default_medicine_discount smallint NOT NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE accounts_clinic DROP COLUMN IF EXISTS default_medicine_discount;",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='clinic',
                    name='default_medicine_discount',
                    field=models.PositiveSmallIntegerField(
                        default=0,
                        help_text='Default discount % pre-filled on every pharmacy bill at this clinic (0 = no discount).'
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
