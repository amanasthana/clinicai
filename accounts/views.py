from django.shortcuts import render, redirect
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

from .forms import StyledAuthForm, ClinicSetupForm, AdminUserForm, AddStaffForm, ClinicRegistrationForm, ContactForm
from .models import Clinic, StaffMember, ClinicRegistrationRequest, ContactMessage


def login_view(request):
    """Clinic staff login. Redirects to reception dashboard on success."""
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    # First-time: no clinic registered yet
    if not Clinic.objects.exists():
        return redirect('accounts:clinic_setup')

    form = StyledAuthForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        if not hasattr(user, 'staff_profile') and not user.is_superuser:
            messages.error(request, 'Your account is not linked to any clinic. Contact your admin.')
            return render(request, 'accounts/login.html', {'form': form})
        login(request, user)
        next_url = request.GET.get('next', '/')
        return redirect(next_url)

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


@login_required
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


@login_required
def staff_list_view(request):
    """List all staff at the logged-in user's clinic."""
    clinic = request.user.staff_profile.clinic
    staff = clinic.staff.select_related('user').order_by('role', 'display_name')
    return render(request, 'accounts/staff_list.html', {'staff': staff, 'clinic': clinic})


@login_required
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
        StaffMember.objects.create(
            user=user,
            clinic=clinic,
            role=cd['role'],
            display_name=cd['display_name'],
            qualification=cd.get('qualification', ''),
            registration_number=cd.get('registration_number', ''),
        )
        messages.success(request, f"{cd['display_name']} added successfully.")
        return redirect('accounts:staff_list')

    return render(request, 'accounts/add_staff.html', {'form': form, 'clinic': clinic})


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
        messages.error(request, f'Approval failed: {e}')
        return redirect('accounts:admin_panel')

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


@login_required
def letterhead_view(request):
    """Upload and configure clinic letterhead for prescription printing."""
    staff = request.user.staff_profile
    if staff.role not in ('admin', 'doctor'):
        messages.error(request, 'Only clinic admins and doctors can manage letterhead.')
        return redirect('reception:dashboard')

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
    """Superuser-only: re-apply password hash from a ClinicRegistrationRequest to its user."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Not authorized.')

    reg = ClinicRegistrationRequest.objects.get(pk=pk)
    try:
        user = User.objects.get(username=reg.phone)
        user.password = reg.password_hash
        user.save(update_fields=['password'])
        messages.success(request, f'Password reset for {reg.phone} ({reg.doctor_name}). They can now log in with the password they set during registration.')
    except User.DoesNotExist:
        messages.error(request, f'No user found with username {reg.phone}. Was the approval run?')
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
    has_staff = hasattr(u, 'staff_profile')
    return JsonResponse({
        'exists': True,
        'phone': phone,
        'is_active': u.is_active,
        'has_staff_profile': has_staff,
        'role': u.staff_profile.role if has_staff else None,
        'clinic': u.staff_profile.clinic.name if has_staff else None,
        'date_joined': str(u.date_joined),
    })
