"""
Data migration: set correct permission flags for all existing admin/doctor
StaffMembers who were created before the set_permissions_from_role call was
added to approve_registration_view and add_clinic_view.
"""
from django.db import migrations

ROLE_PERMISSIONS = {
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
}


def fix_permissions(apps, schema_editor):
    StaffMember = apps.get_model('accounts', 'StaffMember')
    to_update = []
    for sm in StaffMember.objects.filter(role__in=['admin', 'doctor']):
        preset = ROLE_PERMISSIONS.get(sm.role, {})
        changed = False
        for flag, value in preset.items():
            if not getattr(sm, flag, False):
                setattr(sm, flag, value)
                changed = True
        if changed:
            to_update.append(sm)
    if to_update:
        StaffMember.objects.bulk_update(to_update, list(ROLE_PERMISSIONS['admin'].keys()))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_clinic_default_discount'),
    ]

    operations = [
        migrations.RunPython(fix_permissions, migrations.RunPython.noop),
    ]
