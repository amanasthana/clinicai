"""The one-off "ClinicAI is now MedlynAI" announcement email."""

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.password_reset import SUPPORT_WHATSAPP, _greeting_context

CAMPAIGN = 'rebrand-medlynai-2026'
SUBJECT = 'ClinicAI is now MedlynAI'

SAME_ITEMS = [
    'Your <strong>login and password</strong>',
    'Every <strong>patient, prescription, bill and stock record</strong>',
    'Your <strong>clinic settings, staff, letterhead</strong> and favourite medicines',
]

NEW_TILES = [
    [
        {'icon': '🌐', 'bg': '#EFF6FF', 'title': 'New address',
         'text': '<strong style="color:#0F172A;">medlynai.com</strong>. The old ClinicAI link forwards automatically.'},
        {'icon': '🔐', 'bg': '#F5F3FF', 'title': 'Reset your own password',
         'text': 'Tap <em>Forgot password?</em> on the sign-in page and get a secure link by email instantly.'},
    ],
    [
        {'icon': '🧾', 'bg': '#ECFDF5', 'title': 'New prescription look',
         'text': 'Printed prescriptions and WhatsApp messages now carry the MedlynAI name.'},
        {'icon': '⚡', 'bg': '#FFF7ED', 'title': 'Same app, one tap away',
         'text': 'Add medlynai.com to your phone home screen for instant access between patients.'},
    ],
]


def recipients():
    """Active users with an email, one entry per address (case-insensitive).
    When several accounts share an address, personalise with the earliest one
    that belongs to a clinic (so the greeting has a name and clinic)."""
    from accounts.models import StaffMember
    staff_ids = set(StaffMember.objects.values_list('user_id', flat=True))
    by_email = {}
    for u in User.objects.filter(is_active=True).exclude(email='').order_by('pk'):
        key = u.email.strip().lower()
        current = by_email.get(key)
        if current is None or (current.pk not in staff_ids and u.pk in staff_ids):
            by_email[key] = u
    return by_email


def campaign_status():
    """Counts for the admin panel: everyone, sent, pending, sent in the last hour."""
    from datetime import timedelta
    from .models import EmailCampaignSend
    everyone = recipients()
    sends = EmailCampaignSend.objects.filter(campaign=CAMPAIGN)
    sent_emails = set(sends.values_list('email', flat=True))
    pending = [(e, u) for e, u in everyone.items() if e not in sent_emails]
    return {
        'total': len(everyone),
        'sent': len(sent_emails & set(everyone)),
        'pending': pending,
        'pending_count': len(pending),
        'last_hour': sends.filter(sent_at__gte=timezone.now() - timedelta(hours=1)).count(),
        'recent': list(sends.select_related('user').order_by('-sent_at')[:15]),
    }


def send_batch(limit):
    """Send to up to `limit` pending recipients now. Stops at the first Azure
    throttle (HTTP 429). Returns (sent, failed, throttled)."""
    from .models import EmailCampaignSend
    sent = failed = 0
    for email, user in campaign_status()['pending'][:limit]:
        try:
            if not build_message(email, user).send():
                failed += 1
                continue
        except Exception as exc:
            if getattr(exc, 'status_code', None) == 429:
                return sent, failed, True
            failed += 1
            continue
        EmailCampaignSend.objects.get_or_create(campaign=CAMPAIGN, email=email, defaults={'user': user})
        sent += 1
    return sent, failed, False


def build_message(email, user=None):
    ctx = {
        **(_greeting_context(user) if user else {'display_name': 'Doctor', 'clinic_name': '', 'login_id': ''}),
        'email': email,
        'same_items': SAME_ITEMS,
        'new_tiles': NEW_TILES,
        'sent_on': timezone.localdate(),
        'login_url': f'https://{settings.CANONICAL_HOST}/accounts/login/',
        'brand_logo_url': f'https://{settings.CANONICAL_HOST}/static/img/medlynai-logo-white-full.png',
        'site_url': f'https://{settings.CANONICAL_HOST}',
        'support_whatsapp': SUPPORT_WHATSAPP,
        'year': timezone.localdate().year,
    }
    text = render_to_string('accounts/emails/rebrand_announcement.txt', ctx)
    html = render_to_string('accounts/emails/rebrand_announcement.html', ctx)
    msg = EmailMultiAlternatives(SUBJECT, text, settings.DEFAULT_FROM_EMAIL, [email])
    msg.attach_alternative(html, 'text/html')
    return msg
