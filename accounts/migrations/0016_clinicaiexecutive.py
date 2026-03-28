from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0015_staffmember_show_registration_on_rx')]
    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS accounts_clinicaiexecutive (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(150) NOT NULL,
                    gender VARCHAR(1) NOT NULL,
                    mobile VARCHAR(10) NOT NULL UNIQUE,
                    city VARCHAR(100) NOT NULL DEFAULT '',
                    state VARCHAR(100) NOT NULL DEFAULT 'Maharashtra',
                    aadhaar_last4 VARCHAR(4) NOT NULL,
                    aadhaar_hash VARCHAR(64) NOT NULL,
                    photo VARCHAR(100),
                    status VARCHAR(12) NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    approved_at TIMESTAMPTZ
                );
                ALTER TABLE accounts_clinicregistrationrequest
                ADD COLUMN IF NOT EXISTS referred_by_mobile VARCHAR(10) NOT NULL DEFAULT '';
            """,
            reverse_sql="""
                DROP TABLE IF EXISTS accounts_clinicaiexecutive;
                ALTER TABLE accounts_clinicregistrationrequest
                DROP COLUMN IF EXISTS referred_by_mobile;
            """,
            state_operations=[
                migrations.CreateModel(
                    name='ClinicAIExecutive',
                    fields=[
                        ('id', models.AutoField(primary_key=True)),
                        ('name', models.CharField(max_length=150)),
                        ('gender', models.CharField(max_length=1, choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')])),
                        ('mobile', models.CharField(max_length=10, unique=True)),
                        ('city', models.CharField(max_length=100, blank=True)),
                        ('state', models.CharField(max_length=100, default='Maharashtra')),
                        ('aadhaar_last4', models.CharField(max_length=4)),
                        ('aadhaar_hash', models.CharField(max_length=64)),
                        ('photo', models.ImageField(upload_to='executives/', null=True, blank=True)),
                        ('status', models.CharField(max_length=12, choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending')),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('approved_at', models.DateTimeField(null=True, blank=True)),
                    ],
                    options={'ordering': ['name']},
                ),
                migrations.AddField(
                    model_name='clinicregistrationrequest',
                    name='referred_by_mobile',
                    field=models.CharField(max_length=10, blank=True, default=''),
                ),
            ],
        ),
    ]
