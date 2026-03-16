import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils.http import urlencode
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('accounts')

from .forms import StyledAuthForm, ClinicSetupForm, AdminUserForm, AddStaffForm, ClinicRegistrationForm, ContactForm
from .models import Clinic, StaffMember, ClinicRegistrationRequest, ContactMessage
from .permissions import require_permission, set_permissions_from_role, ROLE_PERMISSIONS, ALL_PERMISSION_FLAGS


def login_view(request):
    """Clinic staff login. Redirects to reception dashboard on success."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    # First-time: no clinic registered yet
    if not Clinic.objects.exists():
        return redirect('accounts:clinic_setup')

    form = StyledAuthForm(request, data=request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            if not user.is_superuser and not StaffMember.objects.filter(user=user).exists():
                logger.warning('LOGIN_NO_PROFILE user=%s', form.cleaned_data.get('username'))
                messages.error(request, 'Your account is not linked to any clinic. Contact your admin.')
                return render(request, 'accounts/login.html', {'form': form})
            login(request, user)
            next_url = request.GET.get('next', '/')
            return redirect(next_url)
        else:
            typed_username = request.POST.get('username', '').strip()
            user_exists = (
                User.objects.filter(username=typed_username).exists() or
                User.objects.filter(email__iexact=typed_username).exists()
            ) if typed_username else False
            if typed_username and not user_exists:
                login_hint = f'No account found for "{typed_username}". Check if the clinic was approved by the admin.'
            else:
                login_hint = 'Incorrect password. Please try again.'
            logger.warning('LOGIN_FAILED username=%s user_exists=%s', typed_username, user_exists)
            return render(request, 'accounts/login.html', {'form': form, 'login_hint': login_hint})

    return render(request, 'accounts/login.html', {'form': form})


@require_POST
def logout_view(request):
    """Log out and redirect to login."""
    logout(request)
    return redirect('accounts:login')


def clinic_setup_view(request):
    """
    First-time setup: create clinic + admin user.
    Only accessible when no clinic exists yet.
    """
    if Clinic.objects.exists():
        return redirect('accounts:login')

    clinic_form = ClinicSetupForm(request.POST or None, prefix='clinic')
    user_form = AdminUserForm(request.POST or None, prefix='user')

    if request.method == 'POST' and clinic_form.is_valid() and user_form.is_valid():
        clinic = clinic_form.save()
        cd = user_form.cleaned_data
        user = User.objects.create_user(
            username=cd['username'],
            password=cd['password'],
            first_name=cd['first_name'],
            last_name=cd['last_name'],
        )
        StaffMember.objects.create(
            user=user,
            clinic=clinic,
            role='admin',
            display_name=cd['display_name'],
            qualification=cd.get('qualification', ''),
            registration_number=cd.get('registration_number', ''),
        )
        login(request, user)
        messages.success(request, f'Welcome to ClinicAI! {clinic.name} is ready.')
        return redirect('reception:dashboard')

    return render(request, 'accounts/setup.html', {
        'clinic_form': clinic_form,
        'user_form': user_form,
    })


@require_permission('can_manage_staff')
def plan_view(request):
    """Show the clinic's current plan, today's usage, and upgrade options."""
    from prescription.models import Prescription

    clinic = request.user.staff_profile.clinic
    today = timezone.now().date()
    daily_limit = getattr(settings, 'FREE_DAILY_RX_LIMIT', 30)
    daily_count = Prescription.objects.filter(
        visit__clinic=clinic,
        created_at__date=today,
    ).count()
    remaining = max(0, daily_limit - daily_count)
    percent_used = min(100, int(daily_count / daily_limit * 100)) if daily_limit else 0

    # Last 7 days history
    from datetime import timedelta
    from reception.models import Visit
    week_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        count = Prescription.objects.filter(visit__clinic=clinic, created_at__date=d).count()
        week_data.append({'date': d, 'count': count, 'at_limit': count >= daily_limit})

    return render(request, 'accounts/plan.html', {
        'clinic': clinic,
        'daily_count': daily_count,
        'daily_limit': daily_limit,
        'remaining': remaining,
        'percent_used': percent_used,
        'week_data': week_data,
    })


@require_permission('can_manage_staff')
def staff_list_view(request):
    """List all staff at the logged-in user's clinic."""
    clinic = request.user.staff_profile.clinic
    staff = clinic.staff.select_related('user').order_by('role', 'display_name')
    return render(request, 'accounts/staff_list.html', {'staff': staff, 'clinic': clinic})


@require_permission('can_manage_staff')
def add_staff_view(request):
    """Add a new staff member to the clinic."""
    clinic = request.user.staff_profile.clinic
    form = AddStaffForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        user = User.objects.create_user(
            username=cd['username'],
            password=cd['password'],
            first_name=cd['first_name'],
            last_name=cd['last_name'],
        )
        sm = StaffMember.objects.create(
            user=user,
            clinic=clinic,
            role=cd['role'],
            display_name=cd['display_name'],
            qualification=cd.get('qualification', ''),
            registration_number=cd.get('registration_number', ''),
        )
        set_permissions_from_role(sm)
        sm.save()
        messages.success(request, f"{cd['display_name']} added successfully.")
        return redirect('accounts:staff_list')

    import json as _json
    return render(request, 'accounts/add_staff.html', {
        'form': form,
        'clinic': clinic,
        'role_permissions': ROLE_PERMISSIONS,
        'role_permissions_json': _json.dumps(ROLE_PERMISSIONS),
    })


@require_permission('can_manage_staff')
def edit_staff_view(request, pk):
    """Edit an existing staff member's details and permission flags."""
    my_clinic = request.user.staff_profile.clinic
    sm = get_object_or_404(StaffMember, pk=pk, clinic=my_clinic)

    if request.method == 'POST':
        # Basic fields
        sm.display_name = request.POST.get('display_name', '').strip() or sm.display_name
        sm.qualification = request.POST.get('qualification', '').strip()
        sm.registration_number = request.POST.get('registration_number', '').strip()
        new_role = request.POST.get('role', sm.role)
        sm.role = new_role

        # If "reset to role defaults" was requested, apply preset then override with POSTed checkboxes
        if request.POST.get('reset_to_role'):
            set_permissions_from_role(sm)
        else:
            # Save each flag from checkboxes
            for flag in ALL_PERMISSION_FLAGS:
                setattr(sm, flag, request.POST.get(flag) == 'on')

        # Guard: cannot remove can_manage_staff from yourself if you're the only admin
        if sm.user == request.user and not sm.can_manage_staff:
            other_admins = my_clinic.staff.filter(can_manage_staff=True).exclude(pk=sm.pk)
            if not other_admins.exists():
                messages.error(request, 'You cannot remove staff management access from yourself — you are the only admin.')
                return redirect('accounts:edit_staff', pk=pk)

        sm.save()
        messages.success(request, f'{sm.display_name} updated.')
        return redirect('accounts:staff_list')

    import json as _json
    return render(request, 'accounts/edit_staff.html', {
        'sm': sm,
        'clinic': my_clinic,
        'role_permissions': ROLE_PERMISSIONS,
        'all_flags': ALL_PERMISSION_FLAGS,
        'role_permissions_json': _json.dumps(ROLE_PERMISSIONS),
    })


@require_permission('can_manage_staff')
@require_POST
def delete_staff_view(request, pk):
    """Remove a staff member from this clinic. Does not delete the Django User."""
    my_clinic = request.user.staff_profile.clinic
    sm = get_object_or_404(StaffMember, pk=pk, clinic=my_clinic)

    # Cannot delete yourself
    if sm.user == request.user:
        messages.error(request, 'You cannot remove yourself from the clinic.')
        return redirect('accounts:staff_list')

    name = sm.display_name
    sm.delete()
    messages.success(request, f'{name} has been removed from the clinic.')
    return redirect('accounts:staff_list')


def register_view(request):
    """Public self-registration for new clinics."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    form = ClinicRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        reg = form.save()
        return redirect('accounts:register_success')

    return render(request, 'accounts/register.html', {'form': form})


def register_success_view(request):
    """Thank-you page shown after registration form submitted."""
    return render(request, 'accounts/register_success.html')


def admin_panel_view(request):
    """ClinicAI platform admin panel — superuser only. Lists all registration requests."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Not authorized.')

    pending = ClinicRegistrationRequest.objects.filter(status='pending')
    approved = ClinicRegistrationRequest.objects.filter(status='approved').order_by('-reviewed_at')[:20]
    rejected = ClinicRegistrationRequest.objects.filter(status='rejected').order_by('-reviewed_at')[:10]
    contact_messages = ContactMessage.objects.all()
    unread_count = contact_messages.filter(read=False).count()

    return render(request, 'accounts/admin_panel.html', {
        'pending': pending,
        'approved': approved,
        'rejected': rejected,
        'contact_messages': contact_messages,
        'unread_count': unread_count,
    })


from django.views.decorators.http import require_POST as _require_POST

@_require_POST
def approve_registration_view(request, pk):
    """Approve a registration: create Clinic + User + StaffMember."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Not authorized.')

    from django.db import transaction

    reg = ClinicRegistrationRequest.objects.get(pk=pk, status='pending')

    try:
        with transaction.atomic():
            # Create clinic
            clinic = Clinic.objects.create(
                name=reg.clinic_name,
                city=reg.city,
                state=reg.state,
                phone=reg.clinic_phone,
            )

            # Create user (phone = username)
            user = User(
                username=reg.phone,
                email=reg.email,
                first_name=reg.doctor_name.split()[0] if reg.doctor_name else '',
                last_name=' '.join(reg.doctor_name.split()[1:]) if reg.doctor_name else '',
            )
            user.password = reg.password_hash   # already hashed by make_password
            user.save()

            # Create staff member
            StaffMember.objects.create(
                user=user,
                clinic=clinic,
                role='admin',
                display_name=reg.doctor_name,
                qualification=reg.qualification,
                registration_number=reg.registration_number,
            )

            # Mark as approved
            reg.status = 'approved'
            reg.reviewed_at = timezone.now()
            reg.save()

    except Exception as e:
        logger.error('APPROVAL_FAILED pk=%s error=%s', pk, e, exc_info=True)
        messages.error(request, f'Approval failed: {e}')
        return redirect('accounts:admin_panel')

    logger.info('APPROVAL_OK clinic=%s phone=%s', reg.clinic_name, reg.phone)
    messages.success(request, f'{reg.clinic_name} approved! Login: {reg.phone} / [password set at registration]. Send WhatsApp.')
    return redirect('accounts:admin_panel')


@_require_POST
def reject_registration_view(request, pk):
    """Reject a registration request."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Not authorized.')

    reg = ClinicRegistrationRequest.objects.get(pk=pk, status='pending')
    reg.status = 'rejected'
    reg.reviewed_at = timezone.now()
    reg.admin_notes = request.POST.get('notes', '')
    reg.save()

    messages.info(request, f'{reg.clinic_name} registration rejected.')
    return redirect('accounts:admin_panel')


def contact_view(request):
    """Public contact form — anyone can send a message."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    form = ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('accounts:contact_success')

    return render(request, 'accounts/contact.html', {'form': form})


def contact_success_view(request):
    return render(request, 'accounts/contact_success.html')


@require_POST
def mark_contact_read_view(request, pk):
    """Toggle read/unread on a contact message."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Not authorized.')
    msg = ContactMessage.objects.get(pk=pk)
    msg.read = not msg.read
    msg.save()
    return redirect('accounts:admin_panel')


@login_required
@require_POST
def update_preference_api(request):
    """Update doctor preferences (e.g. show_rx_remarks)."""
    import json
    from django.http import JsonResponse
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    staff = request.user.staff_profile
    if 'show_rx_remarks' in data:
        staff.show_rx_remarks = bool(data['show_rx_remarks'])
        staff.save(update_fields=['show_rx_remarks'])
    return JsonResponse({'ok': True})


@require_permission('can_manage_staff')
def letterhead_view(request):
    """Upload and configure clinic letterhead for prescription printing."""
    staff = request.user.staff_profile
    clinic = staff.clinic

    if request.method == 'POST':
        use_lh = request.POST.get('use_letterhead') == 'on'  # radio: 'on' or 'off'
        height = int(request.POST.get('letterhead_height_mm') or 0)

        update_fields = ['use_letterhead', 'letterhead_height_mm']
        clinic.use_letterhead = use_lh
        clinic.letterhead_height_mm = max(0, min(height, 180))

        if 'letterhead_image' in request.FILES:
            # Delete old image if present
            if clinic.letterhead_image:
                clinic.letterhead_image.delete(save=False)
            clinic.letterhead_image = request.FILES['letterhead_image']
            update_fields.append('letterhead_image')

        if request.POST.get('remove_letterhead') == '1':
            if clinic.letterhead_image:
                clinic.letterhead_image.delete(save=False)
            clinic.letterhead_image = None
            clinic.use_letterhead = False
            update_fields = ['letterhead_image', 'use_letterhead', 'letterhead_height_mm']

        clinic.save(update_fields=update_fields)
        messages.success(request, 'Letterhead settings saved.')
        return redirect('accounts:letterhead')

    return render(request, 'accounts/letterhead.html', {'clinic': clinic})


@_require_POST
def reset_clinic_password_view(request, pk):
    """Superuser-only: ensure the clinic account exists and password is correct."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Not authorized.')

    from django.db import transaction

    reg = ClinicRegistrationRequest.objects.get(pk=pk)

    try:
        with transaction.atomic():
            # Ensure Clinic exists
            clinic = Clinic.objects.filter(name=reg.clinic_name, city=reg.city).first()
            if not clinic:
                clinic = Clinic.objects.create(
                    name=reg.clinic_name, city=reg.city,
                    state=reg.state, phone=reg.clinic_phone,
                )

            # Ensure User exists with correct password
            user, created = User.objects.get_or_create(
                username=reg.phone,
                defaults={
                    'email': reg.email,
                    'first_name': reg.doctor_name.split()[0] if reg.doctor_name else '',
                    'last_name': ' '.join(reg.doctor_name.split()[1:]) if reg.doctor_name else '',
                }
            )
            # Always re-apply the password hash from registration
            user.password = reg.password_hash
            user.save(update_fields=['password'])

            # Ensure StaffMember exists
            if not StaffMember.objects.filter(user=user).exists():
                StaffMember.objects.create(
                    user=user, clinic=clinic, role='admin',
                    display_name=reg.doctor_name,
                    qualification=reg.qualification,
                    registration_number=reg.registration_number,
                )

            # Mark approved if not already
            reg.status = 'approved'
            reg.reviewed_at = reg.reviewed_at or timezone.now()
            reg.save()

        action = 'created' if created else 'fixed'
        messages.success(request, f'Account {action} for {reg.phone} ({reg.doctor_name}). They can now log in with their registration password.')
    except Exception as e:
        logger.error('FIX_ACCOUNT_FAILED pk=%s error=%s', pk, e, exc_info=True)
        messages.error(request, f'Fix failed: {e}. Make sure migrations are up to date: python manage.py migrate')

    return redirect('accounts:admin_panel')


@login_required
@require_POST
def switch_clinic_view(request):
    """Set the active clinic by storing a StaffMember PK in the session."""
    from django.http import JsonResponse as _JsonResponse
    staff_id = request.POST.get('staff_id')
    if not staff_id:
        messages.error(request, 'No clinic specified.')
        return redirect('reception:dashboard')

    try:
        staff_id = int(staff_id)
    except (ValueError, TypeError):
        messages.error(request, 'Invalid clinic selection.')
        return redirect('reception:dashboard')

    # Verify this membership belongs to the current user
    membership = StaffMember.objects.filter(pk=staff_id, user=request.user).select_related('clinic').first()
    if not membership:
        messages.error(request, 'You do not have access to that clinic.')
        return redirect('reception:dashboard')

    request.session['active_staff_id'] = staff_id
    messages.success(request, f'Switched to {membership.clinic.name}.')
    next_url = request.POST.get('next', '/')
    return redirect(next_url)


@login_required
def add_clinic_view(request):
    """Self-serve: create a new clinic and add the current user as a staff member."""
    if request.method == 'POST':
        clinic_name = request.POST.get('clinic_name', '').strip()
        city = request.POST.get('city', '').strip()
        address = request.POST.get('address', '').strip()
        phone = request.POST.get('clinic_phone', '').strip()
        role = request.POST.get('role', 'doctor')
        display_name = request.POST.get('display_name', '').strip()
        qualification = request.POST.get('qualification', '').strip()
        registration_number = request.POST.get('registration_number', '').strip()

        if not clinic_name or not display_name:
            messages.error(request, 'Clinic name and your display name are required.')
            return redirect('accounts:add_clinic')

        clinic = Clinic.objects.create(
            name=clinic_name,
            city=city,
            address=address,
            phone=phone,
        )
        sm = StaffMember.objects.create(
            user=request.user,
            clinic=clinic,
            role=role,
            display_name=display_name,
            qualification=qualification,
            registration_number=registration_number,
        )
        # Immediately switch to the new clinic
        request.session['active_staff_id'] = sm.pk
        messages.success(request, f'{clinic_name} added. You are now working at this clinic.')
        return redirect('reception:dashboard')

    # GET: show form — no clinic list exposed
    return render(request, 'accounts/add_clinic.html')


def _send_otp_fast2sms(phone, otp):
    """Send OTP via Fast2SMS Dev API. Returns (success, error_message)."""
    import requests as _req
    api_key = settings.FAST2SMS_API_KEY
    if not api_key:
        logger.error('FAST2SMS_API_KEY not configured')
        return False, 'SMS service not configured.'
    try:
        resp = _req.get(
            'https://www.fast2sms.com/dev/bulkV2',
            params={
                'authorization': api_key,
                'variables_values': str(otp),
                'route': 'otp',
                'numbers': phone,
            },
            timeout=8,
        )
        data = resp.json()
        logger.info('FAST2SMS_RESPONSE phone=%s data=%s', phone, data)
        if data.get('return'):
            return True, None
        # message can be a list or a plain string depending on error type
        raw = data.get('message', 'SMS delivery failed.')
        err_msg = raw[0] if isinstance(raw, list) else str(raw)
        logger.error('FAST2SMS_FAILED phone=%s err=%s', phone, err_msg)
        return False, err_msg
    except Exception as e:
        logger.error('FAST2SMS_ERROR %s', e)
        return False, 'Could not send OTP. Try again.'


def forgot_password_view(request):
    """Step 1: user enters their 10-digit registered mobile number."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    error = None
    if request.method == 'POST':
        import random
        from django.core.cache import cache

        phone = request.POST.get('phone', '').strip()
        if not phone.isdigit() or len(phone) != 10:
            error = 'Enter a valid 10-digit mobile number.'
        else:
            user = User.objects.filter(username=phone).first()
            if not user:
                # Don't reveal whether number exists — show same success message
                request.session['otp_phone'] = phone
                return redirect('accounts:verify_otp')

            otp = str(random.randint(100000, 999999))
            cache.set(f'pwd_reset_otp:{phone}', otp, timeout=600)   # 10 min
            cache.set(f'pwd_reset_attempts:{phone}', 0, timeout=600)
            ok, err = _send_otp_fast2sms(phone, otp)
            if not ok:
                error = err
            else:
                request.session['otp_phone'] = phone
                return redirect('accounts:verify_otp')

    return render(request, 'accounts/forgot_password.html', {'error': error})


def verify_otp_view(request):
    """Step 2: user enters the 6-digit OTP."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    from django.core.cache import cache

    phone = request.session.get('otp_phone')
    if not phone:
        return redirect('accounts:forgot_password')

    error = None
    if request.method == 'POST':
        entered = request.POST.get('otp', '').strip()
        attempts = cache.get(f'pwd_reset_attempts:{phone}', 0)

        if attempts >= 5:
            error = 'Too many incorrect attempts. Please request a new OTP.'
        elif not entered.isdigit() or len(entered) != 6:
            error = 'Enter the 6-digit OTP.'
        else:
            stored_otp = cache.get(f'pwd_reset_otp:{phone}')
            if stored_otp is None:
                error = 'OTP has expired. Please request a new one.'
            elif entered != stored_otp:
                cache.set(f'pwd_reset_attempts:{phone}', attempts + 1, timeout=600)
                error = 'Incorrect OTP. Please try again.'
            else:
                # OTP correct — grant reset token
                cache.delete(f'pwd_reset_otp:{phone}')
                cache.delete(f'pwd_reset_attempts:{phone}')
                cache.set(f'pwd_reset_verified:{phone}', True, timeout=300)  # 5 min to set new password
                return redirect('accounts:reset_password')

    return render(request, 'accounts/verify_otp.html', {'phone': phone, 'error': error})


def resend_otp_view(request):
    """Resend OTP to the same phone stored in session."""
    import random
    from django.core.cache import cache

    phone = request.session.get('otp_phone')
    if not phone:
        return redirect('accounts:forgot_password')

    otp = str(random.randint(100000, 999999))
    cache.set(f'pwd_reset_otp:{phone}', otp, timeout=600)
    cache.set(f'pwd_reset_attempts:{phone}', 0, timeout=600)
    _send_otp_fast2sms(phone, otp)
    messages.success(request, 'A new OTP has been sent.')
    return redirect('accounts:verify_otp')


def reset_password_view(request):
    """Step 3: user sets a new password after OTP is verified."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    from django.core.cache import cache

    phone = request.session.get('otp_phone')
    if not phone or not cache.get(f'pwd_reset_verified:{phone}'):
        messages.error(request, 'Session expired. Please start again.')
        return redirect('accounts:forgot_password')

    error = None
    if request.method == 'POST':
        pw1 = request.POST.get('password1', '')
        pw2 = request.POST.get('password2', '')
        if len(pw1) < 8:
            error = 'Password must be at least 8 characters.'
        elif pw1 != pw2:
            error = 'Passwords do not match.'
        else:
            user = User.objects.filter(username=phone).first()
            if user:
                user.set_password(pw1)
                user.save()
            cache.delete(f'pwd_reset_verified:{phone}')
            del request.session['otp_phone']
            messages.success(request, 'Password changed successfully. Please log in.')
            return redirect('accounts:login')

    return render(request, 'accounts/reset_password.html', {'error': error})


@login_required
def change_password_view(request):
    """Logged-in user changes their own password."""
    from django.contrib.auth import update_session_auth_hash

    error = None
    if request.method == 'POST':
        current = request.POST.get('current_password', '')
        pw1 = request.POST.get('password1', '')
        pw2 = request.POST.get('password2', '')

        if not request.user.check_password(current):
            error = 'Current password is incorrect.'
        elif len(pw1) < 8:
            error = 'New password must be at least 8 characters.'
        elif pw1 != pw2:
            error = 'New passwords do not match.'
        else:
            request.user.set_password(pw1)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Password changed successfully.')
            return redirect('reception:dashboard')

    return render(request, 'accounts/change_password.html', {'error': error})


def check_user_view(request, phone):
    """Superuser-only debug: verify if a registered user account is healthy."""
    from django.http import JsonResponse
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Not authorized'}, status=403)
    try:
        u = User.objects.get(username=phone)
    except User.DoesNotExist:
        return JsonResponse({'exists': False, 'phone': phone})
    first_membership = StaffMember.objects.filter(user=u).select_related('clinic').first()
    has_staff = first_membership is not None
    return JsonResponse({
        'exists': True,
        'phone': phone,
        'is_active': u.is_active,
        'has_staff_profile': has_staff,
        'role': first_membership.role if has_staff else None,
        'clinic': first_membership.clinic.name if has_staff else None,
        'date_joined': str(u.date_joined),
    })
