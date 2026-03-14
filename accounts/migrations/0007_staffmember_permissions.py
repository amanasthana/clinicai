"""
Add 7 permission flag fields + updated_at to StaffMember.
Data migration sets flags from role preset for all existing rows.
"""
from django.db import migrations, models


# Inline role presets — do NOT import from permissions.py; migrations must be self-contained.
_ROLE_PERMISSIONS = {
    'doctor': {
        'can_register_patients': True,
        'can_prescribe':         True,
        'can_view_pharmacy':     True,
        'can_edit_inventory':    True,
        'can_dispense_bill':     True,
        'can_view_analytics':    True,
        'can_manage_staff':      True,
    },
    'admin': {
        'can_register_patients': True,
        'can_prescribe':         True,
        'can_view_pharmacy':     True,
        'can_edit_inventory':    True,
        'can_dispense_bill':     True,
        'can_view_analytics':    True,
        'can_manage_staff':      True,
    },
    'receptionist': {
        'can_register_patients': True,
        'can_prescribe':         False,
        'can_view_pharmacy':     False,
        'can_edit_inventory':    False,
        'can_dispense_bill':     False,
        'can_view_analytics':    False,
        'can_manage_staff':      False,
    },
    'pharmacist': {
        'can_register_patients': False,
        'can_prescribe':         False,
        'can_view_pharmacy':     True,
        'can_edit_inventory':    True,
        'can_dispense_bill':     True,
        'can_view_analytics':    False,
        'can_manage_staff':      False,
    },
}


def _apply_role_presets(apps, schema_editor):
    StaffMember = apps.get_model('accounts', 'StaffMember')
    for sm in StaffMember.objects.all():
        preset = _ROLE_PERMISSIONS.get(sm.role, {})
        for flag, value in preset.items():
            setattr(sm, flag, value)
        sm.save(update_fields=list(preset.keys()))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_staffmember_user_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffmember',
            name='can_register_patients',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffmember',
            name='can_prescribe',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffmember',
            name='can_view_pharmacy',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffmember',
            name='can_edit_inventory',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffmember',
            name='can_dispense_bill',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffmember',
            name='can_view_analytics',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffmember',
            name='can_manage_staff',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffmember',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.RunPython(_apply_role_presets, migrations.RunPython.noop),
    ]
