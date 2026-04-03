"""
Supervised Action System — maker-checker controls for sensitive staff operations.

Flow:
  Staff initiates action → SupervisedActionRequest created (pending)
  Doctor/admin sees it on /accounts/supervised/ → approves or denies
  On approval: server executes the action automatically (no re-submission)
  Staff's polling screen reflects the outcome and redirects on success.

Sensitive actions covered:
  bill_reversal   — reverse a pharmacy bill and restore stock
  medicine_return — process a medicine return and restore inventory
  queue_delete    — permanently remove a visit from the queue
"""
import json
import decimal
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone

from .models import SupervisedActionRequest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_supervisor(user):
    """Returns True if the user can approve requests (doctor or admin role)."""
    if user.is_superuser:
        return True
    profile = getattr(user, 'staff_profile', None)
    return profile and (profile.is_doctor or profile.is_admin)


def _get_clinic(user):
    profile = getattr(user, 'staff_profile', None)
    return profile.clinic if profile else None


def _expire_stale(clinic):
    """Requests no longer expire — this is intentionally a no-op."""
    pass


# ── Action executors ──────────────────────────────────────────────────────────

def _execute_bill_reversal(payload, clinic):
    """Reverse entire bill — restore inventory, delete bill so re-dispense is possible."""
    from pharmacy.models import PharmacyBill
    bill_id = payload.get('bill_id')
    bill = PharmacyBill.objects.get(pk=bill_id, clinic=clinic)
    visit = bill.visit
    with transaction.atomic():
        for di in visit.dispensed_items.select_related('batch').all():
            di.batch.quantity += di.quantity_dispensed
            di.batch.save(update_fields=['quantity'])
        visit.dispensed_items.all().delete()
        bill.delete()
    return {'redirect': f'/pharmacy/dispense/{visit.id}/'}


def _execute_medicine_return(payload, clinic):
    """Restore returned medicines to inventory and record the return."""
    from pharmacy.models import PharmacyBill, PharmacyBatch, DispensedItem
    bill_id = payload.get('bill_id')
    returns = payload.get('returns', [])
    bill = PharmacyBill.objects.get(pk=bill_id, clinic=clinic)
    with transaction.atomic():
        total_returned = decimal.Decimal('0.00')
        processed = 0
        for r in returns:
            di_id = r.get('dispensed_item_id')
            return_qty = int(r.get('return_qty', 0) or 0)
            if return_qty <= 0:
                continue
            di = DispensedItem.objects.get(pk=di_id, visit=bill.visit)
            if return_qty > di.quantity_dispensed:
                raise ValueError(
                    f'Cannot return {return_qty} — only {di.quantity_dispensed} were dispensed.')
            batch = PharmacyBatch.objects.select_for_update().get(pk=di.batch_id)
            batch.quantity += return_qty
            batch.save(update_fields=['quantity'])
            di.quantity_returned = (di.quantity_returned or 0) + return_qty
            di.save(update_fields=['quantity_returned'])
            total_returned += di.unit_price * return_qty
            processed += 1
    if processed == 0:
        raise ValueError('No items were returned — quantities were all zero.')
    return {'redirect': f'/pharmacy/bill/{bill.pk}/', 'total_returned': str(total_returned)}


def _execute_queue_delete(payload, clinic):
    """Hard-delete a visit from the reception queue."""
    from reception.models import Visit
    visit_id = payload.get('visit_id')
    visit = Visit.objects.get(id=visit_id, clinic=clinic)
    if hasattr(visit, 'prescription'):
        raise ValueError(
            'Cannot delete — a prescription has already been saved. Use Cancel instead.')
    visit.delete()
    return {'redirect': '/'}


ACTION_EXECUTORS = {
    SupervisedActionRequest.ACTION_BILL_REVERSAL:   _execute_bill_reversal,
    SupervisedActionRequest.ACTION_MEDICINE_RETURN: _execute_medicine_return,
    SupervisedActionRequest.ACTION_QUEUE_DELETE:    _execute_queue_delete,
}


def _run_executor(req):
    """
    Execute the action for an approved request.
    Sets status to approved (success) or failed (exception).
    Always saves the request before returning.
    """
    executor = ACTION_EXECUTORS.get(req.action_type)
    if not executor:
        req.status = SupervisedActionRequest.STATUS_FAILED
        req.failure_detail = f'No executor registered for action type: {req.action_type}'
        req.resolved_at = timezone.now()
        req.save(update_fields=['status', 'failure_detail', 'resolved_at', 'resolved_by'])
        return
    try:
        result = executor(req.action_payload, req.clinic)
        req.result_data = result or {}
        req.status = SupervisedActionRequest.STATUS_APPROVED
        req.resolved_at = timezone.now()
        req.save(update_fields=['status', 'result_data', 'resolved_at', 'resolved_by'])
    except Exception as exc:
        req.status = SupervisedActionRequest.STATUS_FAILED
        req.failure_detail = str(exc)[:500]
        req.resolved_at = timezone.now()
        req.save(update_fields=['status', 'failure_detail', 'resolved_at', 'resolved_by'])


# ── Staff: create request ─────────────────────────────────────────────────────

@login_required
@require_POST
def request_action_api(request):
    """Staff submits a supervised action request. Returns {ok, request_id}."""
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)

    profile = getattr(request.user, 'staff_profile', None)
    if not profile:
        return JsonResponse({'ok': False, 'error': 'No staff profile.'}, status=403)

    action_type = data.get('action_type', '')
    if action_type not in dict(SupervisedActionRequest.ACTION_CHOICES):
        return JsonResponse({'ok': False, 'error': 'Invalid action type.'}, status=400)

    action_payload = data.get('action_payload', {})
    if not isinstance(action_payload, dict):
        return JsonResponse({'ok': False, 'error': 'action_payload must be an object.'}, status=400)

    # Store human-readable change detail lines (medicine names, quantities, etc.)
    # under 'detail_lines' — executors ignore unknown keys, approval/audit UI displays it.
    detail_items = data.get('detail_items', [])
    if isinstance(detail_items, list):
        action_payload['detail_lines'] = [str(d)[:200] for d in detail_items[:30]]

    amount = None
    amount_raw = data.get('amount')
    if amount_raw is not None:
        try:
            amount = decimal.Decimal(str(amount_raw))
        except Exception:
            pass

    req = SupervisedActionRequest.objects.create(
        clinic=profile.clinic,
        action_type=action_type,
        requested_by=request.user,
        requester_name=profile.display_name,
        description=str(data.get('description', ''))[:300],
        patient_name=str(data.get('patient_name', ''))[:120],
        amount=amount,
        reference=str(data.get('reference', ''))[:100],
        staff_note=str(data.get('staff_note', ''))[:300],
        action_payload=action_payload,
    )
    return JsonResponse({'ok': True, 'request_id': str(req.id)})


# ── Staff: poll status ────────────────────────────────────────────────────────

@login_required
def poll_action_api(request, request_id):
    """Staff polls for status of their request. Returns {status, ...}."""
    profile = getattr(request.user, 'staff_profile', None)
    if not profile:
        return JsonResponse({'status': 'error', 'error': 'No profile.'}, status=403)
    try:
        req = SupervisedActionRequest.objects.get(id=request_id, clinic=profile.clinic)
    except SupervisedActionRequest.DoesNotExist:
        return JsonResponse({'status': 'error', 'error': 'Request not found.'}, status=404)

    out = {
        'status': req.status,
        'denial_reason': req.denial_reason,
        'failure_detail': req.failure_detail,
    }
    if req.status == SupervisedActionRequest.STATUS_APPROVED:
        out['redirect'] = req.result_data.get('redirect', '/')
    return JsonResponse(out)


# ── Staff: cancel request ─────────────────────────────────────────────────────

@login_required
@require_POST
def cancel_action_api(request, request_id):
    """Staff cancels their own pending request."""
    profile = getattr(request.user, 'staff_profile', None)
    if not profile:
        return JsonResponse({'ok': False, 'error': 'No profile.'}, status=403)
    try:
        req = SupervisedActionRequest.objects.get(
            id=request_id,
            clinic=profile.clinic,
            requested_by=request.user,
            status=SupervisedActionRequest.STATUS_PENDING,
        )
    except SupervisedActionRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Request not found or already resolved.'}, status=404)
    req.status = SupervisedActionRequest.STATUS_CANCELLED
    req.resolved_at = timezone.now()
    req.save(update_fields=['status', 'resolved_at'])
    return JsonResponse({'ok': True})


# ── Supervisor: pending count (nav badge) ─────────────────────────────────────

@login_required
def pending_count_api(request):
    """Returns {count} of pending requests for the nav badge. Supervisor only."""
    if not _is_supervisor(request.user):
        return JsonResponse({'count': 0})
    clinic = _get_clinic(request.user)
    if not clinic:
        return JsonResponse({'count': 0})
    _expire_stale(clinic)
    count = SupervisedActionRequest.objects.filter(
        clinic=clinic, status=SupervisedActionRequest.STATUS_PENDING).count()
    return JsonResponse({'count': count})


# ── Supervisor: grouped pending (JSON) ────────────────────────────────────────

@login_required
def pending_actions_api(request):
    """Returns pending requests grouped by action_type as JSON. Supervisor only."""
    if not _is_supervisor(request.user):
        return JsonResponse({'ok': False, 'error': 'Supervisor access required.'}, status=403)
    clinic = _get_clinic(request.user)
    if not clinic:
        return JsonResponse({'ok': False, 'error': 'No clinic.'}, status=403)

    _expire_stale(clinic)

    pending = list(
        SupervisedActionRequest.objects.filter(
            clinic=clinic, status=SupervisedActionRequest.STATUS_PENDING
        ).order_by('action_type', 'created_at')
    )

    # Group by action_type, preserving insertion order
    groups = {}
    for req in pending:
        at = req.action_type
        if at not in groups:
            groups[at] = {
                'action_type': at,
                'label': SupervisedActionRequest.ACTION_GROUP_LABELS.get(at, at),
                'icon': SupervisedActionRequest.ACTION_ICONS.get(at, '•'),
                'count': 0,
                'items': [],
            }
        groups[at]['count'] += 1
        groups[at]['items'].append(req.to_dict())

    return JsonResponse({'ok': True, 'groups': list(groups.values()),
                         'total': len(pending)})


# ── Supervisor: resolve single ────────────────────────────────────────────────

@login_required
@require_POST
def resolve_action_api(request, request_id):
    """Doctor/admin approves or denies a single request."""
    if not _is_supervisor(request.user):
        return JsonResponse({'ok': False, 'error': 'Supervisor access required.'}, status=403)
    clinic = _get_clinic(request.user)
    if not clinic:
        return JsonResponse({'ok': False, 'error': 'No clinic.'}, status=403)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)

    decision = data.get('decision')  # 'approve' | 'deny'
    denial_reason = str(data.get('denial_reason', ''))[:300]

    if decision not in ('approve', 'deny'):
        return JsonResponse({'ok': False, 'error': 'decision must be approve or deny.'}, status=400)

    try:
        req = SupervisedActionRequest.objects.get(id=request_id, clinic=clinic)
    except SupervisedActionRequest.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Request not found.'}, status=404)

    if req.status != SupervisedActionRequest.STATUS_PENDING:
        return JsonResponse(
            {'ok': False, 'error': f'Request is already {req.status} — cannot change it.'},
            status=409)

    if req.is_pending_expired:
        req.status = SupervisedActionRequest.STATUS_EXPIRED
        req.save(update_fields=['status'])
        return JsonResponse({'ok': False, 'error': 'Request expired before you could approve it.'}, status=409)

    req.resolved_by = request.user

    if decision == 'approve':
        _run_executor(req)  # sets status to approved or failed, saves
    else:
        req.status = SupervisedActionRequest.STATUS_DENIED
        req.denial_reason = denial_reason
        req.resolved_at = timezone.now()
        req.save(update_fields=['status', 'denial_reason', 'resolved_at', 'resolved_by'])

    return JsonResponse({
        'ok': True,
        'status': req.status,
        'failure_detail': req.failure_detail,
    })


# ── Supervisor: bulk resolve ──────────────────────────────────────────────────

@login_required
@require_POST
def bulk_resolve_api(request):
    """Doctor/admin bulk approves or denies a list of request IDs."""
    if not _is_supervisor(request.user):
        return JsonResponse({'ok': False, 'error': 'Supervisor access required.'}, status=403)
    clinic = _get_clinic(request.user)
    if not clinic:
        return JsonResponse({'ok': False, 'error': 'No clinic.'}, status=403)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)

    request_ids   = data.get('request_ids', [])
    decision      = data.get('decision')
    denial_reason = str(data.get('denial_reason', ''))[:300]

    if decision not in ('approve', 'deny'):
        return JsonResponse({'ok': False, 'error': 'decision must be approve or deny.'}, status=400)
    if not request_ids:
        return JsonResponse({'ok': False, 'error': 'No request IDs provided.'}, status=400)

    reqs = SupervisedActionRequest.objects.filter(
        id__in=request_ids,
        clinic=clinic,
        status=SupervisedActionRequest.STATUS_PENDING,
    )

    results = []
    for req in reqs:
        if req.is_pending_expired:
            req.status = SupervisedActionRequest.STATUS_EXPIRED
            req.save(update_fields=['status'])
            results.append({'id': str(req.id), 'status': 'expired'})
            continue
        req.resolved_by = request.user
        if decision == 'approve':
            _run_executor(req)
        else:
            req.status = SupervisedActionRequest.STATUS_DENIED
            req.denial_reason = denial_reason
            req.resolved_at = timezone.now()
            req.save(update_fields=['status', 'denial_reason', 'resolved_at', 'resolved_by'])
        results.append({
            'id': str(req.id),
            'status': req.status,
            'failure_detail': req.failure_detail,
        })

    return JsonResponse({'ok': True, 'results': results})


# ── Supervisor: HTML page ─────────────────────────────────────────────────────

@login_required
def supervised_pending_view(request):
    """Doctor/admin's real-time approval management page."""
    if not _is_supervisor(request.user):
        return render(request, 'accounts/403.html',
                      {'required_permission': 'doctor or admin role'}, status=403)
    return render(request, 'accounts/supervised_pending.html', {})


# ── Supervisor: Audit log ─────────────────────────────────────────────────────

@login_required
def supervised_log_view(request):
    """Doctor/admin views the last 30 days of resolved supervised actions."""
    if not _is_supervisor(request.user):
        return render(request, 'accounts/403.html',
                      {'required_permission': 'doctor or admin role'}, status=403)
    clinic = _get_clinic(request.user)
    if not clinic:
        return render(request, 'accounts/403.html',
                      {'required_permission': 'clinic membership'}, status=403)

    since = timezone.now() - timedelta(days=30)

    qs = SupervisedActionRequest.objects.filter(
        clinic=clinic,
        created_at__gte=since,
    ).exclude(status=SupervisedActionRequest.STATUS_PENDING).order_by('-created_at')

    # Optional filters from query params
    action_filter = request.GET.get('action_type', '')
    status_filter = request.GET.get('status', '')
    if action_filter in dict(SupervisedActionRequest.ACTION_CHOICES):
        qs = qs.filter(action_type=action_filter)
    if status_filter in dict(SupervisedActionRequest.STATUS_CHOICES):
        qs = qs.filter(status=status_filter)

    # Build display name map for resolved_by users
    reqs = list(qs.select_related('resolved_by'))
    resolver_ids = {r.resolved_by_id for r in reqs if r.resolved_by_id}
    from .models import StaffMember
    resolver_names = {}
    if resolver_ids:
        for sm in StaffMember.objects.filter(user_id__in=resolver_ids, clinic=clinic):
            resolver_names[sm.user_id] = sm.display_name

    for req in reqs:
        req.resolver_display = resolver_names.get(req.resolved_by_id, '')

    return render(request, 'accounts/supervised_log.html', {
        'requests': reqs,
        'action_choices': SupervisedActionRequest.ACTION_CHOICES,
        'status_choices': SupervisedActionRequest.STATUS_CHOICES,
        'current_action': action_filter,
        'current_status': status_filter,
        'clinic': clinic,
    })
