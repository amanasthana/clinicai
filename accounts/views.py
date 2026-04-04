import logging
import hashlib
import io

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils.http import urlencode
from urllib.parse import quote
from django.http import JsonResponse

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('accounts')

from .forms import StyledAuthForm, ClinicSetupForm, AdminUserForm, AddStaffForm, ClinicRegistrationForm, ContactForm
from .models import Clinic, StaffMember, ClinicRegistrationRequest, ContactMessage, PasswordResetRequest, ClinicAIExecutive
from .permissions import require_permission, set_permissions_from_role, ROLE_PERMISSIONS, ALL_PERMISSION_FLAGS


def login_view(request):
    """Clinic staff login. Redirects to reception dashboard on success."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    # First-time: no clinic registered yet
    if not Clinic.objects.exists():
        return redirect('accounts:clinic_setup')

    form = StyledAuthForm(request, data=request.POST or None)

    # ── Step 2: user picked their clinic from the conflict selector ──
    chosen_namespaced = request.POST.get('chosen_namespaced_username', '').strip()
    if request.method == 'POST' and chosen_namespaced:
        password = request.POST.get('password', '')
        from django.contrib.auth import authenticate as _auth
        user = _auth(request, username=chosen_namespaced, password=password)
        if user:
            if not user.is_superuser and not StaffMember.objects.filter(user=user).exists():
                messages.error(request, 'Account not linked to any clinic.')
                return render(request, 'accounts/login.html', {'form': form})
            login(request, user)
            if StaffMember.objects.filter(user=user, must_change_password=True).exists():
                return redirect('accounts:change_password')
            return redirect(request.GET.get('next', '/'))
        else:
            return render(request, 'accounts/login.html', {
                'form': form,
                'login_hint': 'Incorrect password. Please try again.',
            })

    # ── Step 1: normal login attempt ────────────────────────────────
    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            if not user.is_superuser and not StaffMember.objects.filter(user=user).exists():
                logger.warning('LOGIN_NO_PROFILE user=%s', form.cleaned_data.get('username'))
                messages.error(request, 'Your account is not linked to any clinic. Contact your admin.')
                return render(request, 'accounts/login.html', {'form': form})
            login(request, user)
            if StaffMember.objects.filter(user=user, must_change_password=True).exists():
                return redirect('accounts:change_password')
            return redirect(request.GET.get('next', '/'))
        else:
            typed_username = request.POST.get('username', '').strip()
            typed_password = request.POST.get('password', '')

            # Check if same username exists at multiple clinics
            if typed_username and '__' not in typed_username:
                candidates = list(
                    User.objects.filter(username__endswith=f'__{typed_username}')
                    .select_related()
                )
                if len(candidates) > 1:
                    # Build clinic options — only show clinics where password matches
                    # (don't expose clinic names to someone who doesn't know the password)
                    from django.contrib.auth import authenticate as _auth
                    valid_candidates = []
                    for c in candidates:
                        if c.check_password(typed_password):
                            sm = StaffMember.objects.filter(user=c).select_related('clinic').first()
                            if sm:
                                valid_candidates.append({
                                    'namespaced': c.username,
                                    'clinic_name': sm.clinic.name,
                                    'city': sm.clinic.city or '',
                                })
                    if len(valid_candidates) > 1:
                        # Show clinic picker
                        return render(request, 'accounts/login.html', {
                            'form': form,
                            'clinic_picker': valid_candidates,
                            'picker_username': typed_username,
                            'picker_password': typed_password,
                        })
                    elif len(valid_candidates) == 1:
                        # Only one clinic has matching password — log in directly
                        user = User.objects.get(username=valid_candidates[0]['namespaced'])
                        login(request, user)
                        return redirect(request.GET.get('next', '/'))

            user_exists = (
                User.objects.filter(username=typed_username).exists() or
                User.objects.filter(email__iexact=typed_username).exists() or
                User.objects.filter(username__endswith=f'__{typed_username}').exists()
            ) if typed_username else False
            login_hint = (
                f'No account found for "{typed_username}". Check username or contact your admin.'
                if typed_username and not user_exists
                else 'Incorrect password. Please try again.'
            )
            logger.warning('LOGIN_FAILED username=%s', typed_username)
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
            email=cd.get('email', '') or '',
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

    # Carry forward WhatsApp link from a just-completed reset
    wa_reset_url = request.session.pop('wa_reset_url', None)
    wa_reset_name = request.session.pop('wa_reset_name', None)

    from .models import ClinicDeletionRequest
    pending_deletion = ClinicDeletionRequest.objects.filter(clinic=clinic, status='pending').first()

    return render(request, 'accounts/staff_list.html', {
        'staff': staff,
        'clinic': clinic,
        'wa_reset_url': wa_reset_url,
        'wa_reset_name': wa_reset_name,
        'pending_deletion': pending_deletion,
    })


@require_permission('can_manage_staff')
def add_staff_view(request):
    """Add a new staff member to the clinic."""
    clinic = request.user.staff_profile.clinic
    form = AddStaffForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        # Username is globally unique (phone_name format), validated by the form.
        new_username = cd['username']

        user = User.objects.create_user(
            username=new_username,
            password=cd['password'],
            first_name=cd['first_name'],
            last_name=cd['last_name'],
            email=cd.get('email', '') or '',
        )
        # Convert date → aware datetime (end of that day) if supplied
        expires_date = cd.get('access_expires_at')
        expires_dt = None
        if expires_date:
            from datetime import datetime, time
            from django.utils import timezone as tz
            expires_dt = tz.make_aware(datetime.combine(expires_date, time(23, 59, 59)))

        sm = StaffMember.objects.create(
            user=user,
            clinic=clinic,
            role=cd['role'],
            display_name=cd['display_name'],
            phone=cd['phone'],
            qualification=cd.get('qualification', ''),
            registration_number=cd.get('registration_number', ''),
            access_expires_at=expires_dt,
        )
        set_permissions_from_role(sm)
        sm.save()
        messages.success(
            request,
            f"{cd['display_name']} added. Their User ID is: {new_username}"
        )
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
        sm.show_registration_on_rx = request.POST.get('show_registration_on_rx') == 'on'
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

        # Access expiry date
        expires_str = request.POST.get('access_expires_at', '').strip()
        if expires_str:
            from datetime import datetime, time, date as date_type
            from django.utils import timezone as tz
            try:
                expires_date = date_type.fromisoformat(expires_str)
                sm.access_expires_at = tz.make_aware(datetime.combine(expires_date, time(23, 59, 59)))
            except ValueError:
                pass
        else:
            sm.access_expires_at = None  # Clear expiry → permanent access

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
    """Remove a staff member from this clinic and delete their User account completely."""
    my_clinic = request.user.staff_profile.clinic
    sm = get_object_or_404(StaffMember, pk=pk, clinic=my_clinic)

    # Cannot delete yourself
    if sm.user == request.user:
        messages.error(request, 'You cannot remove yourself from the clinic.')
        return redirect('accounts:staff_list')

    # Clinic admin accounts can only be deleted by a Django superuser
    if sm.role == 'admin':
        messages.error(request, 'Clinic admin accounts cannot be deleted by staff. Contact ClinicAI support.')
        return redirect('accounts:staff_list')

    name = sm.display_name
    login_id = sm.login_username
    user = sm.user
    sm.delete()
    # Always delete the underlying Django User so the User ID is freed for future re-registration.
    # Superuser accounts are never touched.
    if not user.is_superuser:
        user.delete()
    messages.success(request, f'{name} ({login_id}) has been removed and their account deleted.')
    return redirect('accounts:staff_list')


def register_view(request):
    """Public self-registration for new clinics."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    form = ClinicRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        reg = form.save()
        referred_by_mobile = request.POST.get('referred_by_mobile', '').strip()
        if referred_by_mobile.isdigit() and len(referred_by_mobile) == 10:
            reg.referred_by_mobile = referred_by_mobile
            reg.save(update_fields=['referred_by_mobile'])
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

    # Annotate each registration with the referring executive's name
    all_regs = list(pending) + list(approved) + list(rejected)
    referred_mobiles = {r.referred_by_mobile for r in all_regs if r.referred_by_mobile}
    exec_by_mobile = {}
    if referred_mobiles:
        for ex in ClinicAIExecutive.objects.filter(mobile__in=referred_mobiles):
            exec_by_mobile[ex.mobile] = ex.name
    for r in all_regs:
        r.referred_exec_name = exec_by_mobile.get(r.referred_by_mobile, '') if r.referred_by_mobile else ''
    contact_messages = ContactMessage.objects.all()
    unread_count = contact_messages.filter(read=False).count()
    pending_pw_resets = PasswordResetRequest.objects.filter(handled=False).select_related('user')
    wa_reset_url = request.session.pop('wa_reset_url', None)
    wa_reset_name = request.session.pop('wa_reset_name', None)

    # Build list of (reg, clinic_pk) pairs for approved registrations (for delete button)
    approved_with_clinic = []
    for reg in approved:
        clinic_pk = None
        try:
            u = User.objects.get(username=reg.phone)
            sm = StaffMember.objects.filter(user=u).select_related('clinic').first()
            if sm:
                clinic_pk = sm.clinic.pk
        except User.DoesNotExist:
            pass
        approved_with_clinic.append((reg, clinic_pk))

    # All clinics (regardless of registration source)
    from .models import ClinicDeletionRequest
    from django.db.models import Count
    all_clinics = Clinic.objects.all().order_by('name').prefetch_related('staff')
    pending_deletions = ClinicDeletionRequest.objects.filter(status='pending').select_related('clinic', 'requested_by')

    # ── Executive earnings: count approved referrals per executive ──
    PAYOUT_PER_CLINIC = 500
    referral_counts = dict(
        ClinicRegistrationRequest.objects.filter(
            status='approved',
        ).exclude(referred_by_mobile='').values('referred_by_mobile')
         .annotate(n=Count('id')).values_list('referred_by_mobile', 'n')
    )
    # Load referred clinics for each executive so we can show their names
    referred_clinic_names = {}  # mobile → [clinic names]
    for reg in ClinicRegistrationRequest.objects.filter(
        status='approved'
    ).exclude(referred_by_mobile='').only('referred_by_mobile', 'clinic_name'):
        referred_clinic_names.setdefault(reg.referred_by_mobile, []).append(reg.clinic_name)

    exec_earnings = []
    for ex in ClinicAIExecutive.objects.filter(status='approved').order_by('name'):
        count = referral_counts.get(ex.mobile, 0)
        ex.clinics_referred = count
        ex.earnings = count * PAYOUT_PER_CLINIC
        ex.referred_clinic_names = referred_clinic_names.get(ex.mobile, [])
        exec_earnings.append(ex)

    exec_earnings.sort(key=lambda e: -e.clinics_referred)  # highest earners first
    total_payable = sum(e.earnings for e in exec_earnings)

    return render(request, 'accounts/admin_panel.html', {
        'pending': pending,
        'approved': approved,
        'rejected': rejected,
        'approved_with_clinic': approved_with_clinic,
        'contact_messages': contact_messages,
        'unread_count': unread_count,
        'pending_pw_resets': pending_pw_resets,
        'wa_reset_url': wa_reset_url,
        'wa_reset_name': wa_reset_name,
        'all_clinics': all_clinics,
        'pending_deletions': pending_deletions,
        'exec_earnings': exec_earnings,
        'total_payable': total_payable,
        'payout_per_clinic': PAYOUT_PER_CLINIC,
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
            sm = StaffMember.objects.create(
                user=user,
                clinic=clinic,
                role='admin',
                display_name=reg.doctor_name,
                qualification=reg.qualification,
                registration_number=reg.registration_number,
            )
            set_permissions_from_role(sm)
            sm.save()

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

            # Flag forced password change for all staff memberships
            StaffMember.objects.filter(user=user).update(must_change_password=True)

            # Ensure StaffMember exists
            if not StaffMember.objects.filter(user=user).exists():
                _sm = StaffMember.objects.create(
                    user=user, clinic=clinic, role='admin',
                    display_name=reg.doctor_name,
                    qualification=reg.qualification,
                    registration_number=reg.registration_number,
                )
                set_permissions_from_role(_sm)
                _sm.save()

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


@_require_POST
def superuser_reset_password_view(request, pk):
    """Superuser resets a user's password from the admin panel password reset request."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Not authorized.')

    import secrets, string
    reset_req = get_object_or_404(PasswordResetRequest, pk=pk)
    user = reset_req.user

    temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
    user.set_password(temp_password)
    user.save()

    # Flag forced change on all memberships
    StaffMember.objects.filter(user=user).update(must_change_password=True)

    # Mark all pending requests for this user as handled
    PasswordResetRequest.objects.filter(user=user, handled=False).update(
        handled=True, handled_at=timezone.now()
    )

    # Build WhatsApp deeplink
    phone = user.username
    wa_text = (
        f"Hello! Your ClinicAI password has been reset. "
        f"Temporary password: {temp_password} — Please log in and change it immediately."
    )
    wa_url = f"https://wa.me/91{phone}?text={quote(wa_text)}"

    messages.success(request, f'Password reset for {user.username}. Temp: {temp_password}')
    request.session['wa_reset_url'] = wa_url
    request.session['wa_reset_name'] = user.username
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
    """Self-serve: create a new clinic and add the current user as a staff member. Doctor-only."""
    if not request.user.is_superuser:
        profile = getattr(request.user, 'staff_profile', None)
        if not profile or not profile.is_doctor:
            return render(request, 'accounts/403.html', {
                'required_permission': 'doctor role',
            }, status=403)

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
        set_permissions_from_role(sm)
        sm.save()
        # Immediately switch to the new clinic
        request.session['active_staff_id'] = sm.pk
        messages.success(request, f'{clinic_name} added. You are now working at this clinic.')
        return redirect('reception:dashboard')

    # GET: show form — no clinic list exposed
    return render(request, 'accounts/add_clinic.html')


@login_required
def change_password_view(request):
    """Logged-in user changes their own password."""
    from django.contrib.auth import update_session_auth_hash

    forced = StaffMember.objects.filter(user=request.user, must_change_password=True).exists()

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
            # Clear forced-change flag on all memberships
            StaffMember.objects.filter(user=request.user, must_change_password=True).update(
                must_change_password=False
            )
            messages.success(request, 'Password changed successfully.')
            return redirect('reception:dashboard')

    return render(request, 'accounts/change_password.html', {'error': error, 'forced': forced})


@login_required
def update_email_view(request):
    """AJAX: save or update the logged-in user's email address."""
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    email = request.POST.get('email', '').strip().lower()
    if not email:
        return JsonResponse({'ok': False, 'error': 'Email address is required.'})
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'ok': False, 'error': 'Enter a valid email address.'})
    # Check not already used by another user
    from django.contrib.auth.models import User as _User
    if _User.objects.filter(email__iexact=email).exclude(pk=request.user.pk).exists():
        return JsonResponse({'ok': False, 'error': 'This email is already linked to another account.'})
    request.user.email = email
    request.user.save(update_fields=['email'])
    return JsonResponse({'ok': True})


def forgot_password_view(request):
    """Forgot password — shows security message; logs reset request for clinic admin to handle."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    submitted = False
    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        if phone:
            try:
                user = User.objects.get(username=phone)
                # Only create one pending request at a time
                PasswordResetRequest.objects.get_or_create(user=user, handled=False)
                logger.info('FORGOT_PASSWORD_REQUEST username=%s', phone)
            except User.DoesNotExist:
                pass  # Don't reveal whether the account exists
        submitted = True

    return render(request, 'accounts/forgot_password.html', {'submitted': submitted})


@require_permission('can_manage_staff')
@require_POST
def staff_reset_password_view(request, pk):
    """Clinic admin resets a staff member's password to a temp value and flags forced change."""
    import secrets
    import string

    my_clinic = request.user.staff_profile.clinic
    sm = get_object_or_404(StaffMember, pk=pk, clinic=my_clinic)

    # Generate a readable temp password
    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(10))

    sm.user.set_password(temp_password)
    sm.user.save()
    sm.must_change_password = True
    sm.save(update_fields=['must_change_password'])

    # Mark any pending reset requests as handled
    PasswordResetRequest.objects.filter(user=sm.user, handled=False).update(
        handled=True,
        handled_at=timezone.now(),
    )

    # Build WhatsApp deeplink for admin to notify the staff member
    phone_number = sm.user.username  # phone is the username
    wa_text = (
        f"Hello {sm.display_name}, your ClinicAI login password has been reset by your admin. "
        f"Temporary password: {temp_password} — Please log in and change it immediately."
    )
    wa_url = f"https://wa.me/91{phone_number}?text={quote(wa_text)}"

    messages.success(
        request,
        f'Password reset for {sm.display_name}. Temp password: {temp_password}. '
        f'They must change it on first login.'
    )
    # Store wa_url in session so template can show the WhatsApp button
    request.session['wa_reset_url'] = wa_url
    request.session['wa_reset_name'] = sm.display_name
    return redirect('accounts:staff_list')


@require_permission('can_manage_staff')
def clinic_edit_view(request):
    """Edit clinic name, address, city, state, phone."""
    clinic = request.user.staff_profile.clinic
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Clinic name is required.')
            return render(request, 'accounts/clinic_edit.html', {'clinic': clinic})
        clinic.name = name
        clinic.address = request.POST.get('address', '').strip()
        clinic.city = request.POST.get('city', '').strip()
        clinic.state = request.POST.get('state', '').strip()
        clinic.phone = request.POST.get('phone', '').strip()
        clinic.drug_license_number = request.POST.get('drug_license_number', '').strip()
        clinic.medical_license_number = request.POST.get('medical_license_number', '').strip()
        clinic.gst_number = request.POST.get('gst_number', '').strip().upper()
        import decimal as _decimal
        try:
            clinic.default_gst_percent = _decimal.Decimal(request.POST.get('default_gst_percent', '0') or '0')
        except Exception:
            clinic.default_gst_percent = _decimal.Decimal('0')
        try:
            clinic.default_opd_fee = _decimal.Decimal(request.POST.get('default_opd_fee', '0') or '0')
            if clinic.default_opd_fee < 0:
                clinic.default_opd_fee = _decimal.Decimal('0')
        except Exception:
            clinic.default_opd_fee = _decimal.Decimal('0')
        clinic.save(update_fields=[
            'name', 'address', 'city', 'state', 'phone',
            'drug_license_number', 'medical_license_number',
            'gst_number', 'default_gst_percent', 'default_opd_fee',
        ])
        messages.success(request, 'Clinic details updated.')
        return redirect('accounts:staff_list')
    return render(request, 'accounts/clinic_edit.html', {'clinic': clinic})


@login_required
def clinic_delete_view(request, pk):
    """Delete a clinic. Superuser only."""
    if not request.user.is_superuser:
        messages.error(request, 'Only superuser can delete clinics.')
        return redirect('accounts:admin_panel')
    clinic = get_object_or_404(Clinic, pk=pk)
    if request.method == 'POST':
        clinic_name = clinic.name
        clinic.delete()
        messages.success(request, f'Clinic "{clinic_name}" has been deleted.')
        return redirect('accounts:admin_panel')
    return render(request, 'accounts/clinic_delete_confirm.html', {'clinic': clinic})


@require_permission('can_manage_staff')
@require_POST
def request_clinic_deletion_view(request):
    """Clinic admin only — submits a deletion request for their clinic."""
    if not request.user.is_superuser and not request.user.staff_profile.is_admin:
        return render(request, 'accounts/403.html', {
            'required_permission': 'clinic admin role',
        }, status=403)
    from .models import ClinicDeletionRequest
    clinic = request.user.staff_profile.clinic
    reason = request.POST.get('reason', '').strip()
    # Prevent duplicate pending requests
    if ClinicDeletionRequest.objects.filter(clinic=clinic, status='pending').exists():
        messages.warning(request, 'A deletion request for this clinic is already pending review.')
        return redirect('accounts:staff_list')
    ClinicDeletionRequest.objects.create(
        clinic=clinic,
        clinic_name_snapshot=clinic.name,
        requested_by=request.user,
        reason=reason,
    )
    messages.success(request, 'Deletion request submitted. You will be notified within 24–48 hours.')
    return redirect('accounts:staff_list')


@login_required
def approve_clinic_deletion_view(request, pk):
    """Superuser approves a clinic deletion request."""
    from .models import ClinicDeletionRequest
    if not request.user.is_superuser:
        return render(request, 'accounts/403.html', status=403)
    req = get_object_or_404(ClinicDeletionRequest, pk=pk, status='pending')
    if request.method == 'POST':
        clinic_name = req.clinic_name_snapshot
        clinic_to_delete = req.clinic
        # Delete request record first (clinic CASCADE would wipe it anyway)
        req.delete()
        clinic_to_delete.delete()  # cascades to all clinic data
        messages.success(request, f'Clinic "{clinic_name}" and all its data have been permanently deleted.')
        return redirect('accounts:admin_panel')
    return render(request, 'accounts/clinic_delete_confirm.html', {'clinic': req.clinic, 'deletion_request': req})


@login_required
@require_POST
def reject_clinic_deletion_view(request, pk):
    """Superuser rejects a clinic deletion request."""
    from .models import ClinicDeletionRequest
    if not request.user.is_superuser:
        return render(request, 'accounts/403.html', status=403)
    req = get_object_or_404(ClinicDeletionRequest, pk=pk, status='pending')
    req.status = 'rejected'
    req.reviewed_at = timezone.now()
    req.save()
    messages.success(request, f'Deletion request for "{req.clinic_name_snapshot}" rejected.')
    return redirect('accounts:admin_panel')


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


# ---------------------------------------------------------------------------
# ClinicAI Executive Network
# ---------------------------------------------------------------------------

INDIAN_STATES = [
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand', 'Karnataka',
    'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya',
    'Mizoram', 'Nagaland', 'Odisha', 'Punjab', 'Rajasthan', 'Sikkim',
    'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand',
    'West Bengal', 'Delhi', 'Jammu and Kashmir', 'Ladakh', 'Chandigarh',
    'Puducherry',
]


def executive_list_view(request):
    """Public directory of approved ClinicAI Executives. Also serves JSON API for live lookup."""
    q = request.GET.get('q', '').strip()
    mobile_param = request.GET.get('mobile', '').strip()
    fmt = request.GET.get('format', '')

    # JSON API: used by clinic registration form for live executive lookup
    if fmt == 'json' and mobile_param:
        try:
            ex = ClinicAIExecutive.objects.get(mobile=mobile_param, status='approved')
            return JsonResponse({'found': True, 'name': ex.name, 'city': ex.city, 'state': ex.state})
        except ClinicAIExecutive.DoesNotExist:
            return JsonResponse({'found': False})

    executives = ClinicAIExecutive.objects.filter(status='approved').order_by('name')
    total_approved = executives.count()

    return render(request, 'accounts/executives.html', {
        'executives': executives,
        'total_approved': total_approved,
    })


def executive_register_view(request):
    """Public form to apply as a ClinicAI Executive."""
    errors = {}
    form_data = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        gender = request.POST.get('gender', '').strip()
        mobile = request.POST.get('mobile', '').strip().replace(' ', '').replace('-', '')
        mobile_confirm = request.POST.get('mobile_confirm', '').strip().replace(' ', '').replace('-', '')
        aadhaar = request.POST.get('aadhaar', '').strip().replace(' ', '').replace('-', '')
        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', 'Maharashtra').strip()
        photo = request.FILES.get('photo')

        form_data = {'name': name, 'gender': gender, 'mobile': mobile, 'city': city, 'state': state}

        if not name:
            errors['name'] = 'Full name is required.'
        elif len(name) > 150:
            errors['name'] = 'Name must be under 150 characters.'

        if gender not in ('M', 'F', 'O'):
            errors['gender'] = 'Please select a gender.'

        if not mobile.isdigit() or len(mobile) != 10:
            errors['mobile'] = 'Enter a valid 10-digit mobile number.'
        elif mobile_confirm != mobile:
            errors['mobile_confirm'] = 'Mobile numbers do not match.'
        elif ClinicAIExecutive.objects.filter(mobile=mobile).exists():
            errors['mobile'] = 'This mobile number is already registered with us.'

        if not aadhaar.isdigit() or len(aadhaar) != 12:
            errors['aadhaar'] = 'Aadhaar must be exactly 12 digits.'
        elif len(set(aadhaar)) == 1:
            errors['aadhaar'] = 'Invalid Aadhaar number.'
        elif aadhaar.startswith('0') or aadhaar.startswith('1'):
            errors['aadhaar'] = 'Invalid Aadhaar number format.'

        if photo:
            if photo.size > 5 * 1024 * 1024:
                errors['photo'] = 'Photo must be under 5 MB.'

        if not errors:
            aadhaar_last4 = aadhaar[-4:]
            aadhaar_hash = hashlib.sha256(aadhaar.encode()).hexdigest()

            exec_obj = ClinicAIExecutive(
                name=name,
                gender=gender,
                mobile=mobile,
                city=city,
                state=state,
                aadhaar_last4=aadhaar_last4,
                aadhaar_hash=aadhaar_hash,
                status='pending',
            )

            # Save first to get a PK, then attach photo using PK (not mobile) in filename
            exec_obj.save()

            if photo:
                try:
                    from PIL import Image as PilImage
                    from django.core.files.base import ContentFile
                    img = PilImage.open(photo)
                    img = img.convert('RGB')
                    img.thumbnail((400, 400), PilImage.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG', quality=70)
                    buf.seek(0)
                    exec_obj.photo.save(
                        f'exec_{exec_obj.pk}.jpg',
                        ContentFile(buf.read()),
                        save=True,
                    )
                except Exception:
                    pass  # skip photo if it fails
            return redirect('accounts:executive_register_success')

    return render(request, 'accounts/executive_register.html', {
        'errors': errors,
        'form_data': form_data,
        'states': INDIAN_STATES,
    })


def executive_register_success_view(request):
    """Confirmation page after executive registration is submitted."""
    return render(request, 'accounts/executive_register_success.html')


def executive_mobile_view(request, pk):
    """Returns full mobile number for an approved executive (AJAX reveal)."""
    from django.http import JsonResponse
    try:
        ex = ClinicAIExecutive.objects.get(pk=pk, status='approved')
        return JsonResponse({'mobile': ex.mobile})
    except ClinicAIExecutive.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
