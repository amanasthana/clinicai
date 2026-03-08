"""
JSON API endpoints for the reception module.
Used by the frontend for live queue updates and patient search.
All responses scoped to the logged-in user's clinic.
"""
import json
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Patient, Visit, next_token_for_clinic


@login_required
def patient_search_api(request):
    """
    Search patients by phone number.
    Returns patient info + last 5 visits if found.
    Requires min 10 digits to prevent broad searches.
    """
    phone = request.GET.get('phone', '').strip().replace(' ', '').replace('-', '')
    if len(phone) < 10:
        return JsonResponse({'found': False})

    clinic = request.user.staff_profile.clinic
    try:
        patient = Patient.objects.get(clinic=clinic, phone=phone)
        visits = list(
            patient.visits.order_by('-visit_date', '-created_at')[:5].values(
                'id', 'visit_date', 'chief_complaint', 'status', 'token_number'
            )
        )
        # Convert UUIDs and dates to strings for JSON serialization
        for v in visits:
            v['id'] = str(v['id'])
            v['visit_date'] = str(v['visit_date'])

        return JsonResponse({
            'found': True,
            'patient': {
                'id': str(patient.id),
                'name': patient.full_name,
                'age': patient.age,
                'gender': patient.gender,
                'gender_display': patient.gender_display,
                'phone': patient.phone,
                'allergies': patient.allergies,
                'blood_group': patient.blood_group,
                'notes': patient.notes,
            },
            'recent_visits': visits,
        })
    except Patient.DoesNotExist:
        return JsonResponse({'found': False, 'phone': phone})


@login_required
def queue_api(request):
    """Return today's queue as JSON for live updates.

    Optional ?status= filter:
      (none)            → all active visits (excludes done/no_show) — default
      all               → every visit today including done
      waiting           → only waiting
      in_consultation   → only in_consultation
      done              → only done
    """
    clinic = request.user.staff_profile.clinic
    today = timezone.now().date()
    status_filter = request.GET.get('status', '').strip()

    qs = Visit.objects.filter(clinic=clinic, visit_date=today).select_related('patient').order_by('token_number')

    if status_filter == 'all':
        pass  # include everything
    elif status_filter in ('waiting', 'in_consultation', 'done', 'no_show'):
        qs = qs.filter(status=status_filter)
    else:
        # default: active only
        qs = qs.exclude(status__in=['done', 'no_show'])

    data = []
    for v in qs:
        data.append({
            'id': str(v.id),
            'patient_id': str(v.patient.id),
            'token': v.token_number,
            'name': v.patient.full_name,
            'age': v.patient.age,
            'gender': v.patient.gender,
            'chief_complaint': v.chief_complaint,
            'status': v.status,
            'vitals_bp': v.vitals_bp,
        })
    return JsonResponse({'queue': data, 'status_filter': status_filter})


@login_required
@require_POST
def visit_status_api(request, pk):
    """Update visit status (waiting → in_consultation → done)."""
    try:
        clinic = request.user.staff_profile.clinic
        visit = Visit.objects.get(id=pk, clinic=clinic)
    except Visit.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Visit not found'}, status=404)

    data = json.loads(request.body)
    new_status = data.get('status')
    valid = dict(Visit.STATUS_CHOICES).keys()
    if new_status not in valid:
        return JsonResponse({'ok': False, 'error': 'Invalid status'}, status=400)

    visit.status = new_status
    if new_status == 'in_consultation' and not visit.called_at:
        visit.called_at = timezone.now()
    elif new_status == 'done' and not visit.completed_at:
        visit.completed_at = timezone.now()
    visit.save()

    return JsonResponse({'ok': True, 'status': visit.status})
