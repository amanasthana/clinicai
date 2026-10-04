from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0021_supervised_no_expiry'),
    ]

    operations = [
        # Raw SQL with IF NOT EXISTS so this is safe to re-run after a partial deploy
        migrations.RunSQL(
            sql="""
                ALTER TABLE accounts_clinic ADD COLUMN IF NOT EXISTS name_hi varchar(200) NOT NULL DEFAULT '';
                ALTER TABLE accounts_clinic ADD COLUMN IF NOT EXISTS address_hi text NOT NULL DEFAULT '';
                ALTER TABLE accounts_staffmember ADD COLUMN IF NOT EXISTS rx_language varchar(2) NOT NULL DEFAULT 'en';
                ALTER TABLE accounts_staffmember ADD COLUMN IF NOT EXISTS display_name_hi varchar(120) NOT NULL DEFAULT '';
                ALTER TABLE accounts_staffmember ADD COLUMN IF NOT EXISTS qualification_hi varchar(200) NOT NULL DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE accounts_clinic DROP COLUMN IF EXISTS name_hi;
                ALTER TABLE accounts_clinic DROP COLUMN IF EXISTS address_hi;
                ALTER TABLE accounts_staffmember DROP COLUMN IF EXISTS rx_language;
                ALTER TABLE accounts_staffmember DROP COLUMN IF EXISTS display_name_hi;
                ALTER TABLE accounts_staffmember DROP COLUMN IF EXISTS qualification_hi;
            """,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='clinic',
                    name='name_hi',
                    field=models.CharField(blank=True, default='', max_length=200),
                ),
                migrations.AddField(
                    model_name='clinic',
                    name='address_hi',
                    field=models.TextField(blank=True, default=''),
                ),
                migrations.AddField(
                    model_name='staffmember',
                    name='rx_language',
                    field=models.CharField(choices=[('en', 'English'), ('hi', 'Hindi only')], default='en',
                                           help_text='Default language of printed prescriptions.', max_length=2),
                ),
                migrations.AddField(
                    model_name='staffmember',
                    name='display_name_hi',
                    field=models.CharField(blank=True, default='', max_length=120),
                ),
                migrations.AddField(
                    model_name='staffmember',
                    name='qualification_hi',
                    field=models.CharField(blank=True, default='', max_length=200),
                ),
            ],
            database_operations=[],
        ),
    ]
