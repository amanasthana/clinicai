"""'Unlimited prescriptions — lifetime gift' email, sent to one clinic group at a time.

Only goes to doctor/admin accounts of the chosen clinic and its linked clinics that
actually have unlimited prescriptions switched on. Each address gets it once.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.password_reset import SUPPORT_WHATSAPP

import logging
logger = logging.getLogger(__name__)

CAMPAIGN = 'unlimited-rx-gift'
SUBJECT = 'A lifetime gift from the MedlynAI team'


def gifted_clinics(clinic):
    """This clinic and its linked clinics that have unlimited switched on."""
    return [c for c in [clinic, *clinic.linked_clinics()] if c.unlimited_prescriptions]


def recipients(clinic):
    """{email: (user, [clinic names])} for doctor/admin accounts of the gifted clinics."""
    from accounts.models import StaffMember
    clinics = gifted_clinics(clinic)
    out = {}
    members = (StaffMember.objects
               .filter(clinic__in=clinics, role__in=['doctor', 'admin'], user__is_active=True)
               .exclude(user__email='')
               .select_related('user', 'clinic').order_by('pk'))
    for sm in members:
        key = sm.user.email.strip().lower()
        user, names = out.get(key, (sm.user, []))
        if sm.clinic.name not in names:
            names.append(sm.clinic.name)
        out[key] = (user, names)
    return out


def already_sent(emails):
    from .models import EmailCampaignSend
    return set(EmailCampaignSend.objects.filter(campaign=CAMPAIGN, email__in=list(emails))
               .values_list('email', flat=True))


def build_message(email, clinic_names):
    ctx = {
        'subject': SUBJECT,
        'clinic_names': clinic_names,
        'login_url': f'https://{settings.CANONICAL_HOST}/accounts/login/',
        'brand_logo_url': f'https://{settings.CANONICAL_HOST}/static/img/medlynai-logo-white-full.png',
        'site_url': f'https://{settings.CANONICAL_HOST}',
        'support_whatsapp': SUPPORT_WHATSAPP,
        'year': timezone.localdate().year,
    }
    text = render_to_string('accounts/emails/unlimited_gift.txt', ctx)
    html = render_to_string('accounts/emails/unlimited_gift.html', ctx)
    msg = EmailMultiAlternatives(SUBJECT, text, settings.DEFAULT_FROM_EMAIL, [email])
    msg.attach_alternative(html, 'text/html')
    return msg


def send_to_clinic(clinic):
    """Send to every recipient who hasn't had it yet. Returns (sent, failed, skipped)."""
    from .models import EmailCampaignSend
    people = recipients(clinic)
    done = already_sent(people)
    sent = failed = 0
    for email, (user, names) in people.items():
        if email in done:
            continue
        try:
            if not build_message(email, names).send():
                failed += 1
                continue
        except Exception as exc:
            logger.error('UNLIMITED_GIFT_EMAIL_FAILED to=%s error=%s', email, exc)
            failed += 1
            continue
        EmailCampaignSend.objects.get_or_create(campaign=CAMPAIGN, email=email, defaults={'user': user})
        logger.info('UNLIMITED_GIFT_EMAIL_SENT to=%s clinics=%s', email, names)
        sent += 1
    return sent, failed, len(done)
