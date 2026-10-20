from django.contrib.auth.models import User
from django.test import TestCase, Client

from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role
from notifications.models import UserNotice

KEY = UserNotice.REBRAND_MEDLYNAI
DISMISS_URL = f'/notifications/notices/{KEY}/dismiss/'


class RebrandNoticeTest(TestCase):

    def setUp(self):
        clinic = Clinic.objects.create(name='Test Clinic', address='1 Test Rd', city='Mumbai', phone='9000000099')
        self.user = User.objects.create_user(username='nurse1', password='testpass123')
        sm = StaffMember.objects.create(user=self.user, clinic=clinic, role='receptionist', display_name='Nurse One')
        set_permissions_from_role(sm)
        sm.tour_completed = True
        sm.save()
        self.client.force_login(self.user)

    def test_existing_user_with_pending_notice_sees_it(self):
        UserNotice.objects.create(user=self.user, key=KEY)
        resp = self.client.get('/')
        self.assertContains(resp, 'id="rebrand-notice"')
        self.assertContains(resp, 'ClinicAI is now MedlynAI')

    def test_new_user_without_notice_does_not_see_it(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="rebrand-notice"')

    def test_dismiss_marks_seen_and_hides_notice(self):
        UserNotice.objects.create(user=self.user, key=KEY)
        resp = self.client.post(DISMISS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(UserNotice.objects.get(user=self.user, key=KEY).seen_at)
        self.assertNotContains(self.client.get('/'), 'id="rebrand-notice"')

    def test_dismiss_only_affects_own_notice(self):
        other = User.objects.create_user(username='doc2', password='testpass123')
        UserNotice.objects.create(user=self.user, key=KEY)
        UserNotice.objects.create(user=other, key=KEY)
        self.client.post(DISMISS_URL)
        self.assertIsNone(UserNotice.objects.get(user=other, key=KEY).seen_at)

    def test_dismiss_requires_post(self):
        self.assertEqual(self.client.get(DISMISS_URL).status_code, 405)

    def test_dismiss_requires_login(self):
        resp = Client().post(DISMISS_URL)
        self.assertEqual(resp.status_code, 302)

    def test_dismiss_requires_csrf_token(self):
        UserNotice.objects.create(user=self.user, key=KEY)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(DISMISS_URL).status_code, 403)
        self.assertIsNone(UserNotice.objects.get(user=self.user, key=KEY).seen_at)

    def test_anonymous_login_page_has_no_notice(self):
        resp = Client().get('/accounts/login/')
        self.assertNotContains(resp, 'id="rebrand-notice"')


class RebrandNoticeMigrationTest(TestCase):

    def test_data_migration_queues_notice_for_existing_users(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module('notifications.migrations.0003_rebrand_notice_for_existing_users')
        u1 = User.objects.create_user(username='a1', password='x')
        u2 = User.objects.create_user(username='a2', password='x')
        mig.queue_notice(apps, None)
        mig.queue_notice(apps, None)  # idempotent
        self.assertEqual(UserNotice.objects.filter(key=KEY, user__in=[u1, u2], seen_at__isnull=True).count(), 2)


class RebrandEmailCommandTest(TestCase):

    def setUp(self):
        from django.core.management import call_command
        self.call = lambda *a: call_command('send_rebrand_email', *a, stdout=__import__('io').StringIO(),
                                            stderr=__import__('io').StringIO())
        clinic = Clinic.objects.create(name='Gupta Clinic', address='1 Rd', city='Agra', phone='9000000098')
        User.objects.create_superuser('platform', 'shared@example.com', 'x-pass-123')
        doc = User.objects.create_user('9444000001', email='Shared@Example.com', password='x-pass-123')
        StaffMember.objects.create(user=doc, clinic=clinic, role='doctor', display_name='Dr. Gupta')
        User.objects.create_user('9444000002', email='nurse@example.com', password='x-pass-123')
        User.objects.create_user('9444000003', password='x-pass-123')                      # no email
        User.objects.create_user('9444000004', email='gone@example.com', password='x', is_active=False)

    def test_dry_run_sends_nothing(self):
        from django.core import mail
        self.call('--dry-run')
        self.assertEqual(len(mail.outbox), 0)

    def test_all_sends_once_per_address_and_is_resumable(self):
        from django.core import mail
        from notifications.models import EmailCampaignSend
        self.call('--all', '--per-hour', '3600000')
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['nurse@example.com', 'shared@example.com'])
        self.assertEqual(EmailCampaignSend.objects.count(), 2)
        self.call('--all', '--per-hour', '3600000')
        self.assertEqual(len(mail.outbox), 2)

    def test_personalises_with_clinic_account(self):
        from django.core import mail
        self.call('--all', '--per-hour', '3600000', '--limit', '1')
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('Dr. Gupta', html)
        self.assertIn('Gupta Clinic', html)
        self.assertEqual(mail.outbox[0].subject, 'ClinicAI is now MedlynAI')

    def test_test_mode_not_recorded(self):
        from django.core import mail
        from notifications.models import EmailCampaignSend
        self.call('--test', 'shared@example.com')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailCampaignSend.objects.count(), 0)


class AnnouncementsPageTest(TestCase):
    URL = '/notifications/announcements/'

    def setUp(self):
        self.su = User.objects.create_superuser('boss', 'boss@example.com', 'x-pass-123')
        for i in range(12):
            User.objects.create_user(f'94550000{i:02d}', email=f'u{i}@example.com', password='x-pass-123')
        self.client.force_login(self.su)

    def test_non_superuser_forbidden(self):
        c = Client()
        c.force_login(User.objects.get(username='9455000000'))
        self.assertEqual(c.get(self.URL).status_code, 403)
        self.assertEqual(c.get(self.URL + 'preview/').status_code, 403)

    def test_page_shows_counts(self):
        resp = self.client.get(self.URL)
        self.assertContains(resp, 'ClinicAI is now MedlynAI')
        self.assertEqual(resp.context['status']['total'], 13)
        self.assertEqual(resp.context['status']['pending_count'], 13)

    def test_preview_renders_email(self):
        resp = self.client.get(self.URL + 'preview/')
        self.assertContains(resp, 'A new name for the app your clinic runs on')

    def test_send_test_not_recorded(self):
        from django.core import mail
        from notifications.models import EmailCampaignSend
        self.client.post(self.URL, {'action': 'test', 'test_email': 'boss@example.com'})
        self.assertEqual([m.to for m in mail.outbox], [['boss@example.com']])
        self.assertEqual(EmailCampaignSend.objects.count(), 0)

    def test_batch_sends_and_records(self):
        from django.core import mail
        from notifications.models import EmailCampaignSend
        self.client.post(self.URL, {'action': 'batch', 'size': '10'})
        self.assertEqual(len(mail.outbox), 10)
        self.assertEqual(EmailCampaignSend.objects.count(), 10)
        self.client.post(self.URL, {'action': 'batch', 'size': '10'})
        self.assertEqual(len(mail.outbox), 13)                    # only the 3 remaining
        self.assertContains(self.client.get(self.URL), 'Everyone with an email has received')

    def test_batch_respects_hourly_budget(self):
        from django.core import mail
        from notifications.models import EmailCampaignSend
        from notifications.rebrand_email import CAMPAIGN
        EmailCampaignSend.objects.bulk_create(
            [EmailCampaignSend(campaign=CAMPAIGN, email=f'old{i}@example.com') for i in range(85)])
        self.client.post(self.URL, {'action': 'batch', 'size': '10'})
        self.assertEqual(len(mail.outbox), 5)                     # 90 - 85

    def test_invalid_batch_size_rejected(self):
        from django.core import mail
        self.client.post(self.URL, {'action': 'batch', 'size': '999'})
        self.assertEqual(len(mail.outbox), 0)
