"""
Self-service password reset by email.

1. /accounts/forgot-password/ — user enters mobile number, User ID or email.
   Every matching active account that has an email gets a one-time link
   (valid PASSWORD_RESET_TIMEOUT). Accounts without an email fall back to the
   manual PasswordResetRequest queue in the admin panel. The response is the
   same whether or not anything matched, so it never reveals which accounts exist.
2. /accounts/reset/<uidb64>/<token>/ — Django's PasswordResetConfirmView sets
   the new password; we then clear forced-change flags, close any manual
   request and send a "your password was changed" security email.
"""

import logging

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import PasswordResetRequest, StaffMember

logger = logging.getLogger(__name__)

MAX_PER_IDENTIFIER_PER_HOUR = 3
MAX_PER_IP_PER_HOUR = 10
SUPPORT_WHATSAPP = '+91 63666 71221'


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    ip = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    return ip.split(':')[0] if ip.count(':') == 1 else ip  # Azure appends :port to IPv4


def _over_limit(key, limit):
    """Count one attempt against `key`; True once the hourly limit is exceeded."""
    cache.add(key, 0, timeout=60 * 60)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=60 * 60)
        count = 1
    return count > limit


def _matching_users(identifier):
    ident = identifier.strip()
    if not ident:
        return []
    return list(
        User.objects.filter(is_active=True).filter(
            Q(username__iexact=ident) | Q(email__iexact=ident) | Q(username__iendswith=f'__{ident}')
        )
    )


def _greeting_context(user):
    sm = StaffMember.objects.filter(user=user).select_related('clinic').order_by('pk').first()
    return {
        'display_name': (sm.display_name if sm else '') or user.get_full_name() or 'there',
        'clinic_name': sm.clinic.name if sm else '',
        'login_id': user.username,
    }


def _send(user, subject, template, context):
    context = {
        **context,
        'brand_logo_url': f'https://{settings.CANONICAL_HOST}/static/img/medlynai-logo-white-full.png',
        'site_url': f'https://{settings.CANONICAL_HOST}',
        'support_whatsapp': SUPPORT_WHATSAPP,
        'year': timezone.localdate().year,
    }
    text = render_to_string(f'accounts/emails/{template}.txt', context)
    html = render_to_string(f'accounts/emails/{template}.html', context)
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
    msg.attach_alternative(html, 'text/html')
    msg.send(fail_silently=False)


def send_password_reset_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = request.build_absolute_uri(
        reverse('accounts:password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
    )
    _send(user, 'Reset your MedlynAI password', 'password_reset', {
        **_greeting_context(user),
        'reset_url': reset_url,
        'expiry_minutes': settings.PASSWORD_RESET_TIMEOUT // 60,
        'requested_at': timezone.localtime(),
    })


def send_password_changed_email(user):
    _send(user, 'Your MedlynAI password was changed', 'password_changed', {
        **_greeting_context(user),
        'changed_at': timezone.localtime(),
        'login_url': f'https://{settings.CANONICAL_HOST}/accounts/login/',
    })


def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect('reception:dashboard')

    if request.method != 'POST':
        return render(request, 'accounts/forgot_password.html', {})

    identifier = request.POST.get('identifier', '').strip()
    if not identifier:
        return render(request, 'accounts/forgot_password.html', {
            'error': 'Enter your mobile number, User ID or email.',
        })

    limited = (
        _over_limit(f'pwreset:id:{identifier.lower()}', MAX_PER_IDENTIFIER_PER_HOUR)
        | _over_limit(f'pwreset:ip:{_client_ip(request)}', MAX_PER_IP_PER_HOUR)
    )
    if limited:
        logger.warning('PASSWORD_RESET_RATE_LIMITED identifier=%s ip=%s', identifier, _client_ip(request))
    else:
        for user in _matching_users(identifier):
            if user.email:
                try:
                    send_password_reset_email(request, user)
                    logger.info('PASSWORD_RESET_EMAIL_SENT user=%s', user.username)
                except Exception:
                    logger.exception('PASSWORD_RESET_EMAIL_FAILED user=%s', user.username)
                    PasswordResetRequest.objects.get_or_create(user=user, handled=False)
            else:
                # No email on file: keep the manual, admin-assisted route.
                PasswordResetRequest.objects.get_or_create(user=user, handled=False)
                logger.info('PASSWORD_RESET_MANUAL_REQUEST user=%s (no email)', user.username)

    return render(request, 'accounts/forgot_password.html', {
        'submitted': True,
        'expiry_minutes': settings.PASSWORD_RESET_TIMEOUT // 60,
        'support_whatsapp': SUPPORT_WHATSAPP,
    })


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password_reset_complete')

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        StaffMember.objects.filter(user=user, must_change_password=True).update(must_change_password=False)
        PasswordResetRequest.objects.filter(user=user, handled=False).update(
            handled=True, handled_at=timezone.now(),
        )
        logger.info('PASSWORD_RESET_COMPLETED user=%s', user.username)
        try:
            send_password_changed_email(user)
        except Exception:
            logger.exception('PASSWORD_CHANGED_EMAIL_FAILED user=%s', user.username)
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'
