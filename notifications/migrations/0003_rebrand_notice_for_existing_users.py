"""Queue the ClinicAI → MedlynAI rebrand notice for every user that exists when
this migration runs (i.e. at deploy time). Accounts created afterwards never
knew the old name, so they get no row and never see the notice."""

from django.db import migrations

KEY = 'rebrand-medlynai'


def queue_notice(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserNotice = apps.get_model('notifications', 'UserNotice')
    UserNotice.objects.bulk_create(
        [UserNotice(user_id=uid, key=KEY) for uid in User.objects.values_list('id', flat=True)],
        ignore_conflicts=True,
    )


def unqueue_notice(apps, schema_editor):
    apps.get_model('notifications', 'UserNotice').objects.filter(key=KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_user_notice'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(queue_notice, unqueue_notice),
    ]
