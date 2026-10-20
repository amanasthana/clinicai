"""Tests for self-service password reset by email and the ACS email backend."""
import re
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.test import TestCase, override_settings

from accounts.models import Clinic, PasswordResetRequest, StaffMember
from accounts.permissions import set_permissions_from_role

FORGOT = '/accounts/forgot-password/'


def _reset_link(body):
    return re.search(r'https?://[^\s"<]+/accounts/reset/[^\s"<]+/', body).group(0)


class EmailPasswordResetTest(TestCase):

    def setUp(self):
        cache.clear()
        clinic = Clinic.objects.create(name='Sharma Clinic', address='1 Test Rd', city='Lucknow', phone='9000000099')
        self.user = User.objects.create_user(username='9333000001', email='doc@example.com', password='oldpass123')
        sm = StaffMember.objects.create(user=self.user, clinic=clinic, role='doctor', display_name='Dr. Sharma')
        set_permissions_from_role(sm)
        sm.save()
        self.sm = sm

    def _request(self, identifier='9333000001'):
        return self.client.post(FORGOT, {'identifier': identifier}, HTTP_HOST='medlynai.com', secure=True)

    def test_mobile_number_sends_branded_email(self):
        resp = self._request()
        self.assertContains(resp, 'Check your email')
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['doc@example.com'])
        self.assertEqual(m.subject, 'Reset your MedlynAI password')
        html = m.alternatives[0][0]
        self.assertIn('Dr. Sharma', html)
        self.assertIn('Sharma Clinic', html)
        self.assertIn('formerly ClinicAI', html)
        self.assertIn('https://medlynai.com/accounts/reset/', html)
        self.assertIn('https://medlynai.com/accounts/reset/', m.body)

    def test_email_identifier_case_insensitive(self):
        self._request('DOC@Example.com')
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_identifier_same_response_no_email(self):
        resp = self._request('9999999999')
        self.assertContains(resp, 'Check your email')
        self.assertEqual(len(mail.outbox), 0)

    def test_empty_identifier_shows_error(self):
        resp = self._request('')
        self.assertContains(resp, 'Enter your mobile number')
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_flow_changes_password_and_confirms(self):
        self.sm.must_change_password = True
        self.sm.save()
        PasswordResetRequest.objects.create(user=self.user)
        self._request()
        link = _reset_link(mail.outbox[0].body).replace('https://medlynai.com', '')

        # Django swaps the token for a session marker, then shows the form.
        resp = self.client.get(link, HTTP_HOST='medlynai.com', secure=True, follow=True)
        self.assertContains(resp, 'Choose a new password')
        form_url = resp.redirect_chain[-1][0]
        resp = self.client.post(form_url, {'new_password1': 'Fresh-Pass-4821', 'new_password2': 'Fresh-Pass-4821'},
                                HTTP_HOST='medlynai.com', secure=True)
        self.assertRedirects(resp, '/accounts/reset/done/', fetch_redirect_response=False)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Fresh-Pass-4821'))
        self.sm.refresh_from_db()
        self.assertFalse(self.sm.must_change_password)
        self.assertFalse(PasswordResetRequest.objects.filter(user=self.user, handled=False).exists())
        self.assertEqual(mail.outbox[-1].subject, 'Your MedlynAI password was changed')

        # Link is single-use.
        resp = self.client.get(link, HTTP_HOST='medlynai.com', secure=True, follow=True)
        self.assertContains(resp, 'This link has expired')

    def test_weak_password_rejected(self):
        self._request()
        link = _reset_link(mail.outbox[0].body).replace('https://medlynai.com', '')
        resp = self.client.get(link, HTTP_HOST='medlynai.com', secure=True, follow=True)
        resp = self.client.post(resp.redirect_chain[-1][0], {'new_password1': '12345678', 'new_password2': '12345678'},
                                HTTP_HOST='medlynai.com', secure=True)
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('oldpass123'))

    def test_tampered_token_rejected(self):
        resp = self.client.get('/accounts/reset/MQ/bad-token/', HTTP_HOST='medlynai.com', secure=True, follow=True)
        self.assertContains(resp, 'This link has expired')

    def test_rate_limit_per_identifier(self):
        for _ in range(5):
            self._request()
        self.assertEqual(len(mail.outbox), 3)

    def test_user_without_email_falls_back_to_manual_request(self):
        u = User.objects.create_user(username='9333000002', password='x-pass-123')
        self._request('9333000002')
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(PasswordResetRequest.objects.filter(user=u, handled=False).exists())

    def test_inactive_user_gets_nothing(self):
        self.user.is_active = False
        self.user.save()
        self._request()
        self.assertEqual(len(mail.outbox), 0)

    def test_logged_in_change_password_sends_confirmation(self):
        self.client.force_login(self.user)
        self.client.post('/accounts/change-password/', {
            'current_password': 'oldpass123', 'password1': 'newpass9876', 'password2': 'newpass9876',
        })
        self.assertEqual(mail.outbox[-1].subject, 'Your MedlynAI password was changed')

    def test_change_password_page_shows_recovery_email(self):
        self.client.force_login(self.user)
        resp = self.client.get('/accounts/change-password/')
        self.assertContains(resp, 'Recovery email')
        self.assertContains(resp, 'doc@example.com')


@override_settings(ACS_EMAIL_ENDPOINT='https://example.communication.azure.com',
                   DEFAULT_FROM_EMAIL='MedlynAI <DoNotReply@example.azurecomm.net>',
                   EMAIL_ALLOWED_RECIPIENTS=[])
class AzureEmailBackendTest(TestCase):

    def _send(self, to):
        from core.email_backend import AzureCommunicationEmailBackend
        client = MagicMock()
        backend = AzureCommunicationEmailBackend()
        with patch.object(AzureCommunicationEmailBackend, '_get_client', return_value=client):
            m = EmailMultiAlternatives('Subj', 'text body', None, to)
            m.attach_alternative('<p>html</p>', 'text/html')
            n = backend.send_messages([m])
        return n, client

    def test_builds_acs_payload(self):
        n, client = self._send(['a@example.com'])
        self.assertEqual(n, 1)
        payload = client.begin_send.call_args[0][0]
        self.assertEqual(payload['senderAddress'], 'DoNotReply@example.azurecomm.net')
        self.assertEqual(payload['recipients']['to'], [{'address': 'a@example.com'}])
        self.assertEqual(payload['content'], {'subject': 'Subj', 'plainText': 'text body', 'html': '<p>html</p>'})

    @override_settings(EMAIL_ALLOWED_RECIPIENTS=['me@example.com'])
    def test_allowlist_blocks_other_recipients(self):
        n, client = self._send(['someone-else@example.com'])
        self.assertEqual(n, 0)
        client.begin_send.assert_not_called()

    @override_settings(EMAIL_ALLOWED_RECIPIENTS=['me@example.com'])
    def test_allowlist_allows_listed_recipient(self):
        n, client = self._send(['ME@example.com', 'other@example.com'])
        self.assertEqual(n, 1)
        self.assertEqual(client.begin_send.call_args[0][0]['recipients']['to'], [{'address': 'ME@example.com'}])
