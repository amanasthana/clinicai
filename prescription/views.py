import json
import logging
from datetime import timedelta
from urllib.parse import quote

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone

from reception.models import Visit
from .models import Prescription, PrescriptionMedicine, MedicalTerm
from pharmacy.models import DoctorFavorite
from .services import generate_prescription, get_differentials, get_investigations, deidentify_clinical_note

logger = logging.getLogger(__name__)

# Simple in-memory rate limit store {user_id: [timestamps]}
_rate_limit_store: dict = {}
RATE_LIMIT_MAX = 5       # max calls
RATE_LIMIT_WINDOW = 60   # per second window


def _get_daily_rx_count(clinic) -> int:
    """Count prescriptions saved today for this clinic."""
    today = timezone.now().date()
    return Prescription.objects.filter(
        visit__clinic=clinic,
        created_at__date=today,
    ).count()


def _get_daily_rx_limit() -> int:
    from django.conf import settings
    return getattr(settings, 'FREE_DAILY_RX_LIMIT', 30)


def _check_rate_limit(user_id: int) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = timezone.now().timestamp()
    window_start = now - RATE_LIMIT_WINDOW
    timestamps = _rate_limit_store.get(user_id, [])
    # Keep only timestamps within window
    timestamps = [t for t in timestamps if t > window_start]
    if len(timestamps) >= RATE_LIMIT_MAX:
        return False
    timestamps.append(now)
    _rate_limit_store[user_id] = timestamps
    return True


@login_required
def doctor_queue_view(request):
    """
    Doctor's view: today's waiting patients.
    Shows queue ordered by token, with quick 'Start Consultation' action.
    """
    clinic = request.user.staff_profile.clinic
    today = timezone.now().date()

    queue = (
        Visit.objects.filter(clinic=clinic, visit_date=today)
        .exclude(status__in=['done', 'no_show'])
        .select_related('patient')
        .order_by('token_number')
    )
    done_today = Visit.objects.filter(
        clinic=clinic, visit_date=today, status='done'
    ).count()

    return render(request, 'prescription/doctor_queue.html', {
        'queue': queue,
        'clinic': clinic,
        'today': today,
        'done_today': done_today,
    })


@login_required
def consult_view(request, visit_id):
    """
    Main prescription/consultation screen.
    Doctor types clinical notes here; AI generates structured prescription.
    """
    clinic = request.user.staff_profile.clinic
    visit = get_object_or_404(Visit, id=visit_id, clinic=clinic)
    patient = visit.patient

    # Load existing prescription if any
    existing_rx = getattr(visit, 'prescription', None)

    # Past visits for context (last 5, excluding current)
    past_visits = (
        patient.visits.exclude(id=visit.id)
        .order_by('-visit_date')[:5]
        .select_related('prescription')
    )

    doctor = request.user.staff_profile
    favorites = DoctorFavorite.objects.filter(doctor=doctor).select_related('medicine')

    return render(request, 'prescription/consult.html', {
        'visit': visit,
        'patient': patient,
        'clinic': clinic,
        'existing_rx': existing_rx,
        'past_visits': past_visits,
        'doctor': doctor,
        'favorites': favorites,
        'show_rx_remarks': doctor.show_rx_remarks,
    })


@login_required
@require_POST
def generate_prescription_api(request):
    """
    AJAX endpoint: de-identify note → call Claude → return structured prescription.
    Rate limited to 5 requests/minute per user.
    """
    if not _check_rate_limit(request.user.id):
        return JsonResponse(
            {'ok': False, 'error': 'Too many requests. Please wait a moment.'},
            status=429,
        )

    # Daily free-plan limit check
    clinic = request.user.staff_profile.clinic
    daily_count = _get_daily_rx_count(clinic)
    daily_limit = _get_daily_rx_limit()
    if daily_count >= daily_limit:
        return JsonResponse({
            'ok': False,
            'limit_reached': True,
            'count': daily_count,
            'limit': daily_limit,
            'error': 'Daily prescription limit reached.',
        }, status=429)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    raw_note = data.get('clinical_note', '').strip()
    patient_age = data.get('age', 0)
    patient_gender = data.get('gender', 'M')

    if not raw_note:
        return JsonResponse({'ok': False, 'error': 'Clinical note is empty.'}, status=400)

    try:
        prescription_data = generate_prescription(
            raw_note, patient_age, patient_gender,
            doctor=request.user.staff_profile,
            clinic=clinic,
        )
        return JsonResponse({'ok': True, 'prescription': prescription_data})
    except json.JSONDecodeError as e:
        logger.error("Failed to parse AI response as JSON: %s", e)
        return JsonResponse(
            {'ok': False, 'error': 'AI returned an unexpected format. Please try again.'},
            status=500,
        )
    except Exception as e:
        logger.error("Prescription generation error: %s", e)
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def differentials_api(request):
    """
    AJAX endpoint: clinical note → ranked differential diagnoses (Step 1 of diff-dx workflow).
    Rate limited. Returns list of 3-5 diagnoses with probability + reasoning.
    """
    if not _check_rate_limit(request.user.id):
        return JsonResponse({'ok': False, 'error': 'Too many requests. Please wait a moment.'}, status=429)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    raw_note = data.get('clinical_note', '').strip()
    patient_age = data.get('age', 0)
    patient_gender = data.get('gender', 'M')

    if not raw_note:
        return JsonResponse({'ok': False, 'error': 'Clinical note is empty.'}, status=400)

    try:
        result = get_differentials(raw_note, patient_age, patient_gender)
        return JsonResponse({'ok': True, 'differentials': result.get('differentials', [])})
    except json.JSONDecodeError as e:
        logger.error("Failed to parse differentials response: %s", e)
        return JsonResponse({'ok': False, 'error': 'AI returned an unexpected format. Please try again.'}, status=500)
    except Exception as e:
        logger.error("Differentials generation error: %s", e)
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def investigations_api(request):
    """
    AJAX endpoint: confirmed diagnosis → investigations split into Immediate/Elective (Step 2).
    """
    if not _check_rate_limit(request.user.id):
        return JsonResponse({'ok': False, 'error': 'Too many requests. Please wait a moment.'}, status=429)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    selected_diagnosis = data.get('selected_diagnosis', '').strip()
    raw_note = data.get('clinical_note', '').strip()
    patient_age = data.get('age', 0)
    patient_gender = data.get('gender', 'M')

    if not selected_diagnosis:
        return JsonResponse({'ok': False, 'error': 'No diagnosis selected.'}, status=400)

    try:
        result = get_investigations(selected_diagnosis, raw_note, patient_age, patient_gender)
        return JsonResponse({'ok': True, 'investigations': result.get('investigations', {})})
    except json.JSONDecodeError as e:
        logger.error("Failed to parse investigations response: %s", e)
        return JsonResponse({'ok': False, 'error': 'AI returned an unexpected format. Please try again.'}, status=500)
    except Exception as e:
        logger.error("Investigations generation error: %s", e)
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def save_prescription_api(request, visit_id):
    """
    Save the final prescription (AI-generated or manually edited) to the DB.
    Marks the visit as 'done'.
    """
    clinic = request.user.staff_profile.clinic
    visit = get_object_or_404(Visit, id=visit_id, clinic=clinic)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    raw_note = data.get('raw_clinical_note', '')
    rx_data = data.get('prescription', {})

    # Calculate follow-up date
    follow_up_days = rx_data.get('follow_up_days')
    follow_up_date = None
    if follow_up_days and isinstance(follow_up_days, int):
        follow_up_date = timezone.now().date() + timedelta(days=follow_up_days)

    # Create or update prescription record
    rx, created = Prescription.objects.update_or_create(
        visit=visit,
        defaults={
            'doctor': request.user.staff_profile,
            'raw_clinical_note': raw_note,
            'soap_note': rx_data.get('soap_note', ''),
            'diagnosis': rx_data.get('diagnosis', ''),
            'advice': rx_data.get('advice', ''),
            'patient_summary_en': rx_data.get('patient_summary_en', ''),
            'patient_summary_hi': rx_data.get('patient_summary_hi', ''),
            'follow_up_date': follow_up_date,
            'differential_diagnoses': data.get('differential_diagnoses'),
            'investigations': data.get('investigations'),
            'selected_diagnosis': data.get('selected_diagnosis', ''),
            'clinical_evaluation': rx_data.get('clinical_evaluation', ''),
            'investigations_text': rx_data.get('investigations_text', ''),
            'validity_days': int(rx_data.get('validity_days') or 30),
        },
    )

    if not rx.share_token:
        import uuid as _uuid
        rx.share_token = _uuid.uuid4()
        rx.save(update_fields=['share_token'])

    # Save medicines (replace existing)
    rx.medicines.all().delete()
    for i, med in enumerate(rx_data.get('medicines', [])):
        PrescriptionMedicine.objects.create(
            prescription=rx,
            drug_name=med.get('drug_name', ''),
            dosage=med.get('dosage', ''),
            frequency=med.get('frequency', ''),
            duration=med.get('duration', ''),
            notes=med.get('notes', ''),
            order=i,
        )

    # Mark visit as done
    visit.status = 'done'
    visit.completed_at = timezone.now()
    visit.save()

    logger.info(
        "Prescription saved: visit=%s doctor=%s medicines=%d",
        visit_id, request.user.staff_profile.id, rx.medicines.count()
    )

    return JsonResponse({
        'ok': True,
        'rx_id': str(rx.id),
        'print_url': f'/rx/print/{rx.id}/',
    })


@login_required
def print_prescription_view(request, rx_id):
    """
    Print-ready prescription view.
    No external resources — all inline CSS for privacy.
    A5 format, standard Indian prescription layout.
    """
    rx = get_object_or_404(Prescription, id=rx_id)
    # Security: ensure this prescription belongs to user's clinic
    if rx.visit.clinic != request.user.staff_profile.clinic:
        from django.http import Http404
        raise Http404

    # Build WhatsApp share URL with professional message
    wa_url = ''
    patient = rx.visit.patient
    if patient.phone:
        phone_digits = ''.join(filter(str.isdigit, patient.phone))
        if phone_digits and rx.share_token:
            share_url = request.build_absolute_uri(f'/rx/share/{rx.share_token}/')
            clinic_name = rx.visit.clinic.name
            doctor_name = rx.doctor.display_name if rx.doctor else ''

            lines = [
                f'Dear {patient.full_name},',
                '',
                f'Your prescription from *{clinic_name}* is ready.',
                '',
                f'You can view and download your prescription here:',
                share_url,
            ]
            if rx.follow_up_date:
                dr_label = doctor_name if doctor_name else 'your doctor'
                lines += [
                    '',
                    f'Your next follow-up with {dr_label} at {clinic_name} is on '
                    f'*{rx.follow_up_date.strftime("%d %b %Y")}*.',
                    'Please carry this prescription to your next visit.',
                ]
            lines += [
                '',
                f'— {clinic_name}',
            ]
            wa_text = '\n'.join(lines)
            wa_url = f'https://wa.me/91{phone_digits}?text={quote(wa_text)}'

    show_remarks = True
    if rx.doctor:
        show_remarks = rx.doctor.show_rx_remarks

    return render(request, 'prescription/print.html', {
        'rx': rx,
        'visit': rx.visit,
        'patient': patient,
        'clinic': rx.visit.clinic,
        'doctor': rx.doctor,
        'medicines': rx.medicines.all(),
        'wa_url': wa_url,
        'show_remarks': show_remarks,
    })


@login_required
def pharmacy_search_api(request):
    """
    Typeahead: search clinic's pharmacy inventory + medicine catalog by name.
    Returns availability status for inventory items.
    Used by the drug name input on the consult screen.
    """
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    from django.db.models import Q
    from pharmacy.models import PharmacyItem, MedicineCatalog

    clinic = request.user.staff_profile.clinic
    results = []
    seen_names = set()

    # Clinic's own inventory first (with availability status)
    items = (
        PharmacyItem.objects
        .filter(clinic=clinic)
        .filter(Q(medicine__name__icontains=q) | Q(custom_name__icontains=q))
        .select_related('medicine')
        .prefetch_related('batches')[:10]
    )
    for item in items:
        name = item.display_name
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        total_qty = item.total_quantity
        if total_qty == 0:
            avail = 'out'
        elif item.low_stock:
            avail = 'low'
        else:
            avail = 'ok'
        results.append({'name': name, 'availability': avail})

    # Fill remaining from medicine catalog (no availability — not in this clinic's stock)
    if len(results) < 8:
        catalog = (
            MedicineCatalog.objects
            .filter(Q(name__icontains=q) | Q(generic_name__icontains=q))
            .exclude(name__in=seen_names)[:8 - len(results)]
        )
        for med in catalog:
            display = f"{med.form} {med.name}".strip() if med.form else med.name
            if display not in seen_names:
                seen_names.add(display)
                results.append({'name': display, 'availability': None})

    return JsonResponse({'results': results})


@login_required
def suggest_terms(request):
    """Fast local DB typeahead for medical terms — smarter ranked results."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    from django.db.models import Case, When, IntegerField, Value, Q

    qs = MedicalTerm.objects.filter(
        Q(term__icontains=q) | Q(aliases__icontains=q)
    ).annotate(
        match_rank=Case(
            # Exact match
            When(term__iexact=q, then=Value(0)),
            # Starts with query
            When(term__istartswith=q, then=Value(1)),
            # Word boundary match (term contains " query")
            When(term__icontains=' ' + q, then=Value(2)),
            # Contains match
            default=Value(3),
            output_field=IntegerField(),
        )
    ).order_by('match_rank', '-weight', 'term')[:12]

    results = []
    for t in qs:
        results.append({
            'term': t.term,
            'category': t.category,
            'icd': t.icd_code or '',
            'is_snippet': t.category == 'snippet',
        })

    return JsonResponse({'results': results})


@login_required
def favorites_view(request):
    """Show doctor's favourite medicines list."""
    doctor = request.user.staff_profile
    favorites = DoctorFavorite.objects.filter(doctor=doctor).select_related('medicine')
    return render(request, 'prescription/favorites.html', {
        'favorites': favorites,
        'doctor': doctor,
    })


@login_required
@require_POST
def add_favorite_api(request):
    """Add a medicine to doctor's favorites."""
    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    doctor = request.user.staff_profile
    catalog_id = data.get('catalog_id')
    custom_name = data.get('custom_name', '').strip()

    medicine = None
    if catalog_id:
        from pharmacy.models import MedicineCatalog
        try:
            medicine = MedicineCatalog.objects.get(pk=catalog_id)
        except MedicineCatalog.DoesNotExist:
            pass

    if not medicine and not custom_name:
        return JsonResponse({'ok': False, 'error': 'No medicine specified'}, status=400)

    fav = DoctorFavorite.objects.create(
        doctor=doctor,
        medicine=medicine,
        custom_name=custom_name if not medicine else '',
        default_form=data.get('default_form', ''),
        default_dosage=data.get('default_dosage', ''),
        default_frequency=data.get('default_frequency', ''),
        default_duration=data.get('default_duration', ''),
        default_notes=data.get('default_notes', ''),
        sort_order=DoctorFavorite.objects.filter(doctor=doctor).count(),
    )
    return JsonResponse({'ok': True, 'id': fav.pk, 'name': fav.display_name})


@login_required
@require_POST
def remove_favorite_api(request, pk):
    """Remove a medicine from doctor's favorites."""
    doctor = request.user.staff_profile
    from django.shortcuts import get_object_or_404
    fav = get_object_or_404(DoctorFavorite, pk=pk, doctor=doctor)
    fav.delete()
    return JsonResponse({'ok': True})


def public_prescription_view(request, token):
    """Public share link — no login required. Shows full prescription card."""
    rx = get_object_or_404(Prescription, share_token=token)
    show_remarks = True
    if rx.doctor:
        show_remarks = rx.doctor.show_rx_remarks
    return render(request, 'prescription/print.html', {
        'rx': rx,
        'visit': rx.visit,
        'patient': rx.visit.patient,
        'clinic': rx.visit.clinic,
        'doctor': rx.doctor,
        'medicines': rx.medicines.all(),
        'wa_url': '',   # no WA button on public view
        'show_remarks': show_remarks,
        'is_public': True,
    })


@login_required
def favorites_list_api(request):
    """Return doctor's favorites as JSON for consult page quick-add pills."""
    doctor = request.user.staff_profile
    favorites = DoctorFavorite.objects.filter(doctor=doctor).select_related('medicine')
    return JsonResponse({'items': [
        {
            'id': f.pk,
            'name': f.display_name,
            'form': f.default_form,
            'dosage': f.default_dosage,
            'frequency': f.default_frequency,
            'duration': f.default_duration,
            'notes': f.default_notes,
        }
        for f in favorites
    ]})
