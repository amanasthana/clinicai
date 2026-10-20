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
