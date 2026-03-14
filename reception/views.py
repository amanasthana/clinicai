import json
from collections import Counter
from datetime import timedelta

import anthropic

from django.conf import settings
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import require_permission
from .models import Patient, Visit, next_token_for_clinic
from .forms import PatientForm, VitalsForm, QuickVisitForm, PatientEditForm


@require_permission('can_register_patients')
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


@require_permission('can_register_patients')
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


@require_permission('can_register_patients')
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


@require_permission('can_register_patients')
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


@require_permission('can_register_patients')
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


@require_permission('can_view_analytics')
def analytics_view(request):
    """
    Clinical analytics dashboard.
    Shows patient volume trends, top chief complaints, and top prescribed medicines.
    """
    staff = request.user.staff_profile
    clinic = staff.clinic
    today = timezone.now().date()

    # ── Date range picker ──────────────────────────────────────────────────
    range_param = request.GET.get('range', '30')
    try:
        days = int(range_param)
        if days not in (7, 30, 90, 365):
            days = 30
    except ValueError:
        days = 30
    since = today - timedelta(days=days - 1)

    visits_qs = Visit.objects.filter(clinic=clinic, visit_date__gte=since)

    # ── 1. Patient volume — daily counts ──────────────────────────────────
    daily_counts_qs = (
        visits_qs
        .annotate(day=TruncDate('visit_date'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    # Fill in zeros for missing days
    daily_map = {row['day']: row['count'] for row in daily_counts_qs}
    volume_labels = []
    volume_data = []
    for i in range(days):
        d = since + timedelta(days=i)
        volume_labels.append(d.strftime('%d %b'))
        volume_data.append(daily_map.get(d, 0))

    # ── 2. Top chief complaints ─────────────────────────────────────────
    complaints_raw = (
        visits_qs
        .exclude(chief_complaint='')
        .values_list('chief_complaint', flat=True)
    )
    # Tokenise: split on common separators, lowercase, strip
    word_counter: Counter = Counter()
    skip = {'c/o', 'k/o', 'h/o', 'a/h', 'with', 'and', 'the', 'of', 'for',
            'has', 'in', 'on', 'at', 'to', 'no', 'not', 'is', 'was', 'since',
            'days', 'day', 'weeks', 'week', 'months', 'month', 'patient',
            'presenting', 'complaints', 'complaint'}
    import re
    for complaint in complaints_raw:
        # Extract key phrases: split on common punctuation + "since", "with", etc.
        # First try to get phrases like "fever since 3 days" → "fever"
        phrases = re.split(r'[,/\n&+|]', complaint.lower())
        for phrase in phrases:
            phrase = phrase.strip()
            if 2 <= len(phrase) <= 60:
                # Multi-word: keep as-is if short enough, else take first 2 words
                words = phrase.split()
                if len(words) == 1:
                    key = words[0]
                else:
                    # Drop trailing "since X days" clutter → first 2 words
                    key = ' '.join(words[:2])
                # Remove numbers and very short tokens
                key = re.sub(r'\d+', '', key).strip()
                if key and len(key) >= 3 and key not in skip:
                    word_counter[key] += 1
    top_complaints = word_counter.most_common(10)

    # ── 3. Top prescribed medicines ─────────────────────────────────────
    from prescription.models import PrescriptionMedicine
    import re as _re
    drug_names_qs = (
        PrescriptionMedicine.objects
        .filter(prescription__visit__clinic=clinic, prescription__visit__visit_date__gte=since)
        .values_list('drug_name', flat=True)
    )
    drug_counter: Counter = Counter()
    for name in drug_names_qs:
        # Normalise: lowercase, strip form prefix (Tab/Cap/Syp/Inj/Gel/Oint/Cream/Drop)
        clean = _re.sub(r'^(tab\.?|cap\.?|syp\.?|inj\.?|gel|oint\.?|cream|drop|susp\.?)\s+', '', name.strip().lower())
        # Keep just the first word (drug name) up to 30 chars
        first = clean.split()[0] if clean else ''
        if first and len(first) >= 3:
            drug_counter[first.capitalize()] += 1
    top_medicines = drug_counter.most_common(10)

    # ── Summary numbers ───────────────────────────────────────────────────
    total_visits = visits_qs.count()
    total_patients = Patient.objects.filter(clinic=clinic).count()
    new_patients = Patient.objects.filter(clinic=clinic, created_at__date__gte=since).count()
    avg_daily = round(total_visits / days, 1)

    return render(request, 'reception/analytics.html', {
        'clinic': clinic,
        'days': days,
        'since': since,
        'today': today,
        'range_choices': [(7, '7 days'), (30, '30 days'), (90, '3 months'), (365, '1 year')],
        'summary': {
            'total_visits': total_visits,
            'total_patients': total_patients,
            'new_patients': new_patients,
            'avg_daily': avg_daily,
        },
        'volume_labels': json.dumps(volume_labels),
        'volume_data': json.dumps(volume_data),
        'top_complaints': top_complaints,
        'top_medicines': top_medicines,
    })


@login_required
@require_POST
def help_api(request):
    """Streaming SSE — answers questions about ClinicAI using Claude Haiku."""
    import json as _json
    from core.help_content import HELP_SYSTEM_PROMPT

    try:
        data = _json.loads(request.body)
        question = data.get('question', '').strip()[:400]
    except Exception:
        from django.http import JsonResponse
        return JsonResponse({'error': 'Invalid request'}, status=400)

    if not question:
        from django.http import JsonResponse
        return JsonResponse({'error': 'Question is required.'}, status=400)

    # Session-based rate limit: 20 help queries per day
    from django.utils import timezone as _tz
    today_key = f"help_{_tz.now().date()}"
    count = request.session.get(today_key, 0)
    if count >= 20:
        from django.http import JsonResponse
        return JsonResponse({'error': 'You have reached the daily help limit. Try again tomorrow.'}, status=429)
    request.session[today_key] = count + 1

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def _stream():
        try:
            with client.messages.stream(
                model='claude-haiku-4-5-20251001',
                max_tokens=500,
                system=HELP_SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': question}],
            ) as stream:
                for text in stream.text_stream:
                    yield f'data: {_json.dumps({"text": text})}\n\n'
        except Exception as e:
            yield f'data: {_json.dumps({"error": "Something went wrong. Please try again."})}\n\n'
        yield 'data: [DONE]\n\n'

    resp = StreamingHttpResponse(_stream(), content_type='text/event-stream; charset=utf-8')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    return resp
