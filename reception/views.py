from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone

from .models import Patient, Visit, next_token_for_clinic
from .forms import PatientForm, VitalsForm, QuickVisitForm, PatientEditForm


@login_required
def dashboard_view(request):
    """
    Main reception dashboard.
    Shows today's queue + patient phone search bar.
    This is the primary screen for receptionists.
    """
    clinic = request.user.staff_profile.clinic
    today = timezone.now().date()

    queue = (
        Visit.objects.filter(clinic=clinic, visit_date=today)
        .select_related('patient')
        .order_by('token_number')
    )

    # Today's stats
    total_today = queue.count()
    waiting = queue.filter(status='waiting').count()
    in_consult = queue.filter(status='in_consultation').count()
    done = Visit.objects.filter(clinic=clinic, visit_date=today, status='done').count()

    # Weekly stats (last 7 days including today)
    week_ago = today - timedelta(days=6)
    week_visits = Visit.objects.filter(clinic=clinic, visit_date__gte=week_ago).count()
    total_patients = Patient.objects.filter(clinic=clinic).count()
    new_patients_week = Patient.objects.filter(
        clinic=clinic, created_at__date__gte=week_ago
    ).count()

    return render(request, 'reception/dashboard.html', {
        'clinic': clinic,
        'queue': queue,
        'today': today,
        'stats': {
            'total': total_today + done,
            'waiting': waiting,
            'in_consult': in_consult,
            'done': done,
        },
        'week_stats': {
            'visits': week_visits,
            'total_patients': total_patients,
            'new_patients': new_patients_week,
        },
    })


@login_required
def new_patient_view(request):
    """
    Register a new patient and add them to today's queue.
    Pre-fills phone number from query param if coming from search.
    """
    clinic = request.user.staff_profile.clinic
    initial_phone = request.GET.get('phone', '')
    form = PatientForm(request.POST or None, initial={'phone': initial_phone})

    if request.method == 'POST' and form.is_valid():
        patient = form.save(commit=False)
        patient.clinic = clinic

        # Check if patient already exists (same phone)
        existing = Patient.objects.filter(clinic=clinic, phone=patient.phone).first()
        if existing:
            messages.warning(
                request,
                f'{existing.full_name} is already registered with this phone number. '
                f'Adding to today\'s queue.'
            )
            patient = existing
        else:
            patient.save()

        # Create a visit (token)
        chief_complaint = form.cleaned_data.get('chief_complaint', '')
        token = next_token_for_clinic(clinic.id)
        visit = Visit.objects.create(
            patient=patient,
            clinic=clinic,
            token_number=token,
            chief_complaint=chief_complaint,
        )
        messages.success(
            request,
            f'Token #{token} assigned to {patient.full_name}.'
        )
        return redirect('reception:dashboard')

    return render(request, 'reception/new_patient.html', {'form': form, 'clinic': clinic})


@login_required
def patient_detail_view(request, pk):
    """Patient detail + visit history."""
    clinic = request.user.staff_profile.clinic
    patient = get_object_or_404(Patient, id=pk, clinic=clinic)
    visits = patient.visits.order_by('-visit_date', '-created_at')

    quick_form = QuickVisitForm(request.POST or None)
    if request.method == 'POST' and quick_form.is_valid():
        token = next_token_for_clinic(clinic.id)
        Visit.objects.create(
            patient=patient,
            clinic=clinic,
            token_number=token,
            chief_complaint=quick_form.cleaned_data.get('chief_complaint', ''),
        )
        messages.success(request, f'Token #{token} assigned. Patient added to today\'s queue.')
        return redirect('reception:dashboard')

    return render(request, 'reception/patient_detail.html', {
        'patient': patient,
        'visits': visits,
        'quick_form': quick_form,
        'clinic': clinic,
    })


@login_required
def patient_edit_view(request, pk):
    """Edit patient demographics (name, age, gender, allergies, etc.)."""
    clinic = request.user.staff_profile.clinic
    patient = get_object_or_404(Patient, id=pk, clinic=clinic)
    form = PatientEditForm(request.POST or None, instance=patient)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Patient profile updated.')
        return redirect('reception:patient_detail', pk=pk)

    return render(request, 'reception/patient_edit.html', {
        'form': form,
        'patient': patient,
        'clinic': clinic,
    })


@login_required
def visit_detail_view(request, pk):
    """View/edit vitals for a specific visit."""
    clinic = request.user.staff_profile.clinic
    visit = get_object_or_404(Visit, id=pk, clinic=clinic)
    form = VitalsForm(request.POST or None, instance=visit)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Vitals updated.')
        return redirect('reception:dashboard')

    return render(request, 'reception/visit_detail.html', {
        'visit': visit,
        'form': form,
        'clinic': clinic,
    })
