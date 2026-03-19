from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_staffmember_permissions'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Use raw SQL with IF NOT EXISTS so this is safe to re-run
        # even if the column was partially added in a previous failed deployment
        migrations.RunSQL(
            sql="""
                ALTER TABLE accounts_staffmember
                ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false;
            """,
            reverse_sql="""
                ALTER TABLE accounts_staffmember
                DROP COLUMN IF EXISTS must_change_password;
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS accounts_passwordresetrequest (
                    id bigserial PRIMARY KEY,
                    requested_at timestamp with time zone NOT NULL DEFAULT now(),
                    handled boolean NOT NULL DEFAULT false,
                    handled_at timestamp with time zone NULL,
                    user_id integer NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE
                );
            """,
            reverse_sql="DROP TABLE IF EXISTS accounts_passwordresetrequest;",
        ),
        # Tell Django ORM about the new field and model (state-only operations)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffmember',
                    name='must_change_password',
                    field=models.BooleanField(default=False),
                ),
                migrations.CreateModel(
                    name='PasswordResetRequest',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('requested_at', models.DateTimeField(auto_now_add=True)),
                        ('handled', models.BooleanField(default=False)),
                        ('handled_at', models.DateTimeField(null=True, blank=True)),
                        ('user', models.ForeignKey(
                            on_delete=django.db.models.deletion.CASCADE,
                            related_name='reset_requests',
                            to=settings.AUTH_USER_MODEL,
                        )),
                    ],
                    options={'ordering': ['-requested_at']},
                ),
            ],
            database_operations=[],  # DB already handled by RunSQL above
        ),
    ]
