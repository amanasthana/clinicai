"""
Tests for reception: appointment cancellation feature.
"""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from reception.models import Visit, Patient
from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role


# ── Helpers ─────────────────────────────────────────────────────────────────

def make_clinic_and_user(username='rectest', clinic_name='Test Clinic'):
    clinic = Clinic.objects.create(
        name=clinic_name, address='1 Test Rd', city='Mumbai', phone='9000000099',
    )
    user = User.objects.create_user(username=username, password='testpass')
    sm = StaffMember.objects.create(clinic=clinic, user=user, role='admin', display_name='Test Staff')
    set_permissions_from_role(sm)
    sm.save()
    return clinic, user


def make_patient(clinic, name='Ramu Kaka', phone='9000000001'):
    return Patient.objects.create(
        clinic=clinic, full_name=name, phone=phone, gender='M', age=40,
    )


def make_visit(clinic, patient, status='waiting'):
    return Visit.objects.create(
        clinic=clinic,
        patient=patient,
        token_number=1,
        status=status,
        visit_date=timezone.now().date(),
    )


# ── Model tests ──────────────────────────────────────────────────────────────

class VisitCancellationModelTest(TestCase):

    def setUp(self):
        self.clinic, self.user = make_clinic_and_user()
        self.patient = make_patient(self.clinic)

    def test_cancelled_status_in_choices(self):
        statuses = [s[0] for s in Visit.STATUS_CHOICES]
        self.assertIn('cancelled', statuses)

    def test_cancellation_reason_choices_exist(self):
        reasons = [r[0] for r in Visit.CANCELLATION_REASON_CHOICES]
        self.assertIn('patient_called', reasons)
        self.assertIn('rescheduled', reasons)
        self.assertIn('doctor_unavailable', reasons)
        self.assertIn('patient_unwell', reasons)
        self.assertIn('other', reasons)

    def test_cancellation_reason_field_default_blank(self):
        visit = make_visit(self.clinic, self.patient)
        self.assertEqual(visit.cancellation_reason, '')

    def test_cancel_visit_saves_reason(self):
        visit = make_visit(self.clinic, self.patient)
        visit.status = 'cancelled'
        visit.cancellation_reason = 'rescheduled'
        visit.save()
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'cancelled')
        self.assertEqual(visit.cancellation_reason, 'rescheduled')

    def test_status_color_for_cancelled(self):
        visit = make_visit(self.clinic, self.patient, status='cancelled')
        self.assertEqual(visit.status_color, 'red')


# ── API tests ─────────────────────────────────────────────────────────────────

class CancelVisitAPITest(TestCase):

    def setUp(self):
        self.clinic, self.user = make_clinic_and_user()
        self.patient = make_patient(self.clinic)
        self.visit = make_visit(self.clinic, self.patient)
        self.client = Client()
        self.client.login(username='rectest', password='testpass')
        self.url = f'/api/visit/{self.visit.id}/cancel/'

    def _post(self, reason):
        return self.client.post(
            self.url,
            data=json.dumps({'reason': reason}),
            content_type='application/json',
        )

    def test_cancel_visit_sets_status_cancelled(self):
        resp = self._post('patient_called')
        self.assertEqual(resp.status_code, 200)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, 'cancelled')

    def test_cancel_visit_saves_reason(self):
        self._post('rescheduled')
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.cancellation_reason, 'rescheduled')

    def test_cancel_visit_returns_ok_true(self):
        resp = self._post('other')
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['status'], 'cancelled')

    def test_cancel_visit_invalid_reason_returns_400(self):
        resp = self._post('not_a_real_reason')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_cancel_visit_requires_post(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_cancel_visit_requires_login(self):
        anon = Client()
        resp = anon.post(self.url, data=json.dumps({'reason': 'other'}), content_type='application/json')
        self.assertIn(resp.status_code, [302, 403])

    def test_cancel_visit_wrong_clinic_returns_404(self):
        other_clinic, other_user = make_clinic_and_user('other_user', 'Other Clinic')
        other_patient = make_patient(other_clinic, phone='9111111111')
        other_visit = make_visit(other_clinic, other_patient)
        url = f'/api/visit/{other_visit.id}/cancel/'
        resp = self._post('other')  # logged in as self.user (different clinic)
        # Should be 404 because visit doesn't belong to this clinic
        # (We posted to the wrong visit id but we're checking own clinic's visit,
        #  so actually re-target the URL)
        resp2 = self.client.post(url, data=json.dumps({'reason': 'other'}), content_type='application/json')
        self.assertEqual(resp2.status_code, 404)

    def test_cancel_already_done_visit_returns_400(self):
        self.visit.status = 'done'
        self.visit.save()
        resp = self._post('patient_called')
        self.assertEqual(resp.status_code, 400)

    def test_cancel_already_cancelled_visit_returns_400(self):
        self.visit.status = 'cancelled'
        self.visit.cancellation_reason = 'other'
        self.visit.save()
        resp = self._post('rescheduled')
        self.assertEqual(resp.status_code, 400)

    def test_cancel_all_valid_reasons(self):
        valid = ['patient_called', 'rescheduled', 'doctor_unavailable', 'patient_unwell', 'other']
        for reason in valid:
            # Reset visit each time
            self.visit.status = 'waiting'
            self.visit.cancellation_reason = ''
            self.visit.save()
            resp = self._post(reason)
            self.assertEqual(resp.status_code, 200, f"Failed for reason: {reason}")
            self.visit.refresh_from_db()
            self.assertEqual(self.visit.cancellation_reason, reason)


# ── Queue API tests ───────────────────────────────────────────────────────────

class QueueAPIExcludesCancelledTest(TestCase):

    def setUp(self):
        self.clinic, self.user = make_clinic_and_user('qtest', 'Q Clinic')
        self.client = Client()
        self.client.login(username='qtest', password='testpass')
        self.patient = make_patient(self.clinic)

    def test_queue_api_excludes_cancelled_by_default(self):
        Visit.objects.create(
            clinic=self.clinic, patient=self.patient, token_number=1,
            status='cancelled', cancellation_reason='rescheduled',
            visit_date=timezone.now().date(),
        )
        resp = self.client.get('/api/queue/')
        data = resp.json()
        statuses = [v['status'] for v in data['queue']]
        self.assertNotIn('cancelled', statuses)

    def test_queue_api_all_includes_cancelled(self):
        Visit.objects.create(
            clinic=self.clinic, patient=self.patient, token_number=1,
            status='cancelled', cancellation_reason='other',
            visit_date=timezone.now().date(),
        )
        resp = self.client.get('/api/queue/?status=all')
        data = resp.json()
        statuses = [v['status'] for v in data['queue']]
        self.assertIn('cancelled', statuses)

    def test_queue_api_cancelled_filter(self):
        Visit.objects.create(
            clinic=self.clinic, patient=self.patient, token_number=1,
            status='cancelled', cancellation_reason='rescheduled',
            visit_date=timezone.now().date(),
        )
        Visit.objects.create(
            clinic=self.clinic, patient=self.patient, token_number=2,
            status='waiting', visit_date=timezone.now().date(),
        )
        resp = self.client.get('/api/queue/?status=cancelled')
        data = resp.json()
        self.assertEqual(len(data['queue']), 1)
        self.assertEqual(data['queue'][0]['status'], 'cancelled')


# ── Help API tests ────────────────────────────────────────────────────────────

from unittest.mock import patch, MagicMock


class HelpApiTest(TestCase):

    def setUp(self):
        self.clinic, self.user = make_clinic_and_user('helptest', 'Help Clinic')
        self.client = Client()
        self.client.login(username='helptest', password='testpass')
        self.url = '/api/help/'

    def test_help_api_requires_login(self):
        """Anonymous request should redirect to login (302)."""
        anon = Client()
        resp = anon.post(
            self.url,
            data=json.dumps({'question': 'How do I print?'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 302)

    def test_help_api_rejects_empty_question(self):
        """POST with empty question string should return 400."""
        resp = self.client.post(
            self.url,
            data=json.dumps({'question': '   '}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_help_api_rejects_bad_json(self):
        """POST with non-JSON body should return 400."""
        resp = self.client.post(
            self.url,
            data='not json at all',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_help_api_rate_limit(self):
        """After 20 queries today, next request returns 429."""
        session = self.client.session
        from django.utils import timezone
        today_key = f"help_{timezone.now().date()}"
        session[today_key] = 20
        session.save()

        resp = self.client.post(
            self.url,
            data=json.dumps({'question': 'What is ClinicAI?'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 429)
        self.assertIn('error', resp.json())

    @patch('reception.views.anthropic.Anthropic')
    def test_help_api_returns_streaming_response(self, mock_anthropic_class):
        """Valid question with mocked Anthropic client should return 200 SSE stream."""
        # Build mock stream context manager
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
        mock_stream_ctx.__exit__ = MagicMock(return_value=False)
        mock_stream_ctx.text_stream = iter(['Hello', ' world', '!'])

        mock_client = MagicMock()
        mock_client.messages.stream.return_value = mock_stream_ctx
        mock_anthropic_class.return_value = mock_client

        resp = self.client.post(
            self.url,
            data=json.dumps({'question': 'How do I register a patient?'}),
            content_type='application/json',
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/event-stream', resp.get('Content-Type', ''))

        # Consume the streaming response
        content = b''.join(resp.streaming_content).decode('utf-8')
        self.assertIn('data:', content)
        self.assertIn('[DONE]', content)
        # Should contain the streamed text chunks
        self.assertIn('Hello', content)
        self.assertIn('world', content)
