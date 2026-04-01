"""
Role presets and the require_permission decorator.
"""
from functools import wraps
from django.shortcuts import render, redirect
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

# What each role gets by default
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

ALL_PERMISSION_FLAGS = list(ROLE_PERMISSIONS['doctor'].keys())


def set_permissions_from_role(staff_member):
    """Apply the default permission preset for the staff member's role."""
    preset = ROLE_PERMISSIONS.get(staff_member.role, {})
    for flag, value in preset.items():
        setattr(staff_member, flag, value)


def require_permission(flag):
    """
    View decorator. Checks request.user.staff_profile.<flag>.
    Superusers always pass. Returns 403 page if denied.
    If staff access has expired, logs the user out and redirects to login.
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            profile = getattr(request.user, 'staff_profile', None)
            if profile and profile.access_expired:
                logout(request)
                messages.error(
                    request,
                    'Your access has expired. Please contact the clinic administrator.'
                )
                return redirect('accounts:login')
            if profile and getattr(profile, flag, False):
                return view_func(request, *args, **kwargs)
            return render(request, 'accounts/403.html', {
                'required_permission': flag,
            }, status=403)
        return wrapper
    return decorator
