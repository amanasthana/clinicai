from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import gift_email, rebrand_email
from .models import UserNotice

HOURLY_BUDGET = 90                 # under the 100/hour ACS quota; resets share it
BATCH_SIZES = (10, 25, 50)


@login_required
@require_POST
def dismiss_notice(request, key):
    """Mark a one-time notice as seen for the current user."""
    UserNotice.objects.filter(
        user=request.user, key=key, seen_at__isnull=True,
    ).update(seen_at=timezone.now())
    return JsonResponse({'ok': True})


def _superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


@login_required
def announcements_view(request):
    """Superuser control panel for the ClinicAI → MedlynAI announcement email."""
    _superuser(request)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'test':
            to = request.POST.get('test_email', '').strip().lower()
            if not to or '@' not in to:
                messages.error(request, 'Enter an email address for the test.')
            else:
                try:
                    ok = rebrand_email.build_message(to, rebrand_email.recipients().get(to)).send()
                    if ok:
                        messages.success(request, f'Test email sent to {to}. It is not counted as a send.')
                    else:
                        messages.error(request, f'Not sent to {to}: blocked by EMAIL_ALLOWED_RECIPIENTS.')
                except Exception as exc:
                    messages.error(request, f'Sending failed: {exc}')
        elif action == 'batch':
            status = rebrand_email.campaign_status()
            size = int(request.POST.get('size', 0) or 0)
            room = max(HOURLY_BUDGET - status['last_hour'], 0)
            if not 0 < size <= max(BATCH_SIZES):
                messages.error(request, 'Pick a batch size.')
            elif room == 0:
                messages.error(request, 'Hourly sending limit reached. Try again in a little while.')
            else:
                sent, failed, throttled = rebrand_email.send_batch(min(size, room))
                msg = f'Sent {sent} email{"s" if sent != 1 else ""}.'
                if failed:
                    msg += f' {failed} failed (see logs); they stay pending and can be retried.'
                if throttled:
                    msg += ' Azure asked us to slow down; wait a few minutes before the next batch.'
                (messages.warning if (failed or throttled) else messages.success)(request, msg)
        return redirect('notifications:announcements')

    status = rebrand_email.campaign_status()
    room = max(HOURLY_BUDGET - status['last_hour'], 0)
    return render(request, 'notifications/announcements.html', {
        'status': status,
        'room': room,
        'hourly_budget': HOURLY_BUDGET,
        # e.g. pending=5 → [5] instead of three identical 'Send next 5' buttons
        'batch_options': sorted({min(s, status['pending_count']) for s in BATCH_SIZES} - {0}),
        'subject': rebrand_email.SUBJECT,
        'progress': round(100 * status['sent'] / status['total']) if status['total'] else 0,
    })


@login_required
def announcement_preview_view(request):
    """The announcement email exactly as recipients get it (personalised as you)."""
    _superuser(request)
    email = (request.user.email or 'doctor@example.com').lower()
    msg = rebrand_email.build_message(email, rebrand_email.recipients().get(email) or request.user)
    return HttpResponse(msg.alternatives[0][0])


@login_required
def gift_email_view(request, clinic_pk):
    """Superuser: send the 'unlimited prescriptions — lifetime gift' email to one clinic group."""
    _superuser(request)
    from django.shortcuts import get_object_or_404
    from accounts.models import Clinic
    clinic = get_object_or_404(Clinic, pk=clinic_pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'test':
            to = request.POST.get('test_email', '').strip().lower()
            if not to or '@' not in to:
                messages.error(request, 'Enter an email address for the test.')
            else:
                names = [c.name for c in gift_email.gifted_clinics(clinic)] or [clinic.name]
                try:
                    if gift_email.build_message(to, names).send():
                        messages.success(request, f'Test email sent to {to}. The clinic has not been emailed.')
                    else:
                        messages.error(request, f'Not sent to {to}: blocked by EMAIL_ALLOWED_RECIPIENTS.')
                except Exception as exc:
                    messages.error(request, f'Sending failed: {exc}')
        elif action == 'send':
            if not clinic.unlimited_prescriptions:
                messages.error(request, 'Turn on unlimited prescriptions for this clinic first, so the email is true.')
            else:
                sent, failed, skipped = gift_email.send_to_clinic(clinic)
                msg = f'Sent to {sent} recipient{"s" if sent != 1 else ""}.'
                if skipped:
                    msg += f' {skipped} already had it earlier (not sent again).'
                if failed:
                    msg += f' {failed} failed (see logs); you can press Send again to retry them.'
                (messages.warning if failed else messages.success)(request, msg)
        return redirect('notifications:gift_email', clinic_pk=clinic.pk)

    people = gift_email.recipients(clinic)
    done = gift_email.already_sent(people)
    rows = [{'email': e, 'user': u, 'clinics': names, 'sent': e in done} for e, (u, names) in people.items()]
    return render(request, 'notifications/gift_email.html', {
        'clinic': clinic,
        'gifted': gift_email.gifted_clinics(clinic),
        'rows': rows,
        'pending': sum(1 for r in rows if not r['sent']),
        'subject': gift_email.SUBJECT,
    })


@login_required
def gift_email_preview_view(request, clinic_pk):
    """The gift email exactly as the clinic will get it."""
    _superuser(request)
    from django.shortcuts import get_object_or_404
    from accounts.models import Clinic
    clinic = get_object_or_404(Clinic, pk=clinic_pk)
    names = [c.name for c in gift_email.gifted_clinics(clinic)] or [clinic.name]
    msg = gift_email.build_message(request.user.email or 'doctor@example.com', names)
    return HttpResponse(msg.alternatives[0][0])
