"""Clinic self-registration is auto-approved; new doctors/admins get a first-login tour."""
import importlib

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, Client
from django.urls import NoReverseMatch, reverse

from accounts.models import Clinic, ClinicRegistrationRequest, StaffMember, ClinicAIExecutive
from accounts.permissions import set_permissions_from_role


def reg_post(**over):
    data = {
        'clinic_name': 'Sunrise Clinic', 'clinic_type': ClinicRegistrationRequest.CLINIC_TYPES[0][0],
        'city': 'Lucknow', 'state': 'Uttar Pradesh', 'clinic_phone': '05221234567',
        'doctor_name': 'Dr. Meena Verma', 'qualification': 'MBBS', 'registration_number': 'UP-5566',
        'phone': '9123456780', 'email': 'meena@example.com',
        'password': 'StrongPass123', 'password_confirm': 'StrongPass123',
    }
    data.update(over)
    return data


class AutoApprovalTest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_registration_creates_live_clinic_immediately(self):
        resp = self.client.post('/accounts/register/', reg_post())
        self.assertRedirects(resp, '/accounts/register/success/', fetch_redirect_response=False)
        reg = ClinicRegistrationRequest.objects.get(phone='9123456780')
        self.assertEqual(reg.status, 'approved')          # referral payouts count approved rows
        self.assertIsNotNone(reg.reviewed_at)
        user = User.objects.get(username='9123456780')
        sm = StaffMember.objects.get(user=user)
        self.assertEqual(sm.role, 'admin')
        self.assertEqual(sm.clinic.name, 'Sunrise Clinic')
        self.assertEqual(sm.clinic.city, 'Lucknow')
        self.assertEqual(sm.display_name, 'Dr. Meena Verma')
        self.assertTrue(sm.can_prescribe and sm.can_manage_staff and sm.can_register_patients)
        self.assertFalse(sm.tour_completed)
        self.assertFalse(sm.must_change_password)

    def test_can_log_in_right_after_registering(self):
        self.client.post('/accounts/register/', reg_post())
        c = Client()
        resp = c.post('/accounts/login/', {'username': '9123456780', 'password': 'StrongPass123'})
        self.assertEqual(resp.status_code, 302)
        resp = c.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Sunrise Clinic')

    def test_can_log_in_with_email(self):
        self.client.post('/accounts/register/', reg_post())
        c = Client()
        resp = c.post('/accounts/login/', {'username': 'meena@example.com', 'password': 'StrongPass123'})
        self.assertEqual(resp.status_code, 302)

    def test_success_page_says_live_and_links_to_login(self):
        self.client.post('/accounts/register/', reg_post())
        resp = self.client.get('/accounts/register/success/')
        self.assertContains(resp, 'Your clinic is live!')
        self.assertContains(resp, 'Log in to continue')
        self.assertContains(resp, '/accounts/login/?u=9123456780')
        self.assertContains(resp, '9123456780')
        self.assertNotContains(resp, 'review')
        self.assertNotContains(resp, '24 hours')

    def test_success_page_without_session_still_works(self):
        resp = Client().get('/accounts/register/success/')
        self.assertContains(resp, 'Your clinic is live!')
        self.assertContains(resp, 'href="/accounts/login/"')

    def test_login_page_prefills_mobile(self):
        Clinic.objects.create(name='Any', city='X')   # with no clinics, login redirects to setup
        resp = self.client.get('/accounts/login/?u=9123456780')
        self.assertContains(resp, 'value="9123456780"')

    def test_login_prefill_ignores_non_mobile(self):
        Clinic.objects.create(name='Any', city='X')
        resp = self.client.get('/accounts/login/?u=<script>')
        self.assertNotContains(resp, '<script>"')

    def test_register_page_has_no_approval_wording(self):
        resp = self.client.get('/accounts/register/')
        self.assertNotContains(resp, 'review')
        self.assertNotContains(resp, '24 hours')
        self.assertContains(resp, 'goes live instantly')

    def test_referral_kept_and_counted_for_executive_payout(self):
        ClinicAIExecutive.objects.create(name='Ravi MR', mobile='9000000001', city='Lucknow', gender='M', aadhaar_last4='1234', aadhaar_hash='x' * 64,
                                         state='UP', status='approved')
        self.client.post('/accounts/register/', {**reg_post(), 'referred_by_mobile': '9000000001'})
        reg = ClinicRegistrationRequest.objects.get(phone='9123456780')
        self.assertEqual(reg.referred_by_mobile, '9000000001')
        su = User.objects.create_superuser('root', 'r@x.com', 'pw')
        c = Client(); c.force_login(su)
        resp = c.get('/accounts/admin-panel/')
        self.assertContains(resp, 'Sunrise Clinic')
        self.assertEqual(resp.context['total_payable'], resp.context['payout_per_clinic'])

    def test_duplicate_mobile_rejected(self):
        self.client.post('/accounts/register/', reg_post())
        resp = self.client.post('/accounts/register/', reg_post(email='other@example.com', clinic_name='Second'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already registered')
        self.assertEqual(Clinic.objects.filter(name='Second').count(), 0)

    def test_duplicate_email_rejected(self):
        """Email is a login ID — a duplicate would break login for both accounts."""
        self.client.post('/accounts/register/', reg_post())
        resp = self.client.post('/accounts/register/', reg_post(phone='9123456781', email='MEENA@example.com'))
        self.assertContains(resp, 'already used by another account')
        self.assertFalse(User.objects.filter(username='9123456781').exists())

    def test_invalid_form_creates_nothing(self):
        resp = self.client.post('/accounts/register/', reg_post(password_confirm='nope'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ClinicRegistrationRequest.objects.exists())
        self.assertFalse(Clinic.objects.exists())

    def test_failure_rolls_back_everything(self):
        from unittest import mock
        with mock.patch('accounts.registration.set_permissions_from_role', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.client.post('/accounts/register/', reg_post())
        self.assertFalse(ClinicRegistrationRequest.objects.exists())
        self.assertFalse(Clinic.objects.exists())
        self.assertFalse(User.objects.filter(username='9123456780').exists())


class ApprovalRemovedTest(TestCase):

    def test_approve_reject_urls_gone(self):
        for name in ('accounts:approve_registration', 'accounts:reject_registration'):
            with self.assertRaises(NoReverseMatch):
                reverse(name, args=[1])
        su = User.objects.create_superuser('root', 'r@x.com', 'pw')
        c = Client(); c.force_login(su)
        self.assertEqual(c.post('/accounts/admin-panel/approve/1/').status_code, 404)
        self.assertEqual(c.post('/accounts/admin-panel/reject/1/').status_code, 404)

    def test_admin_panel_has_no_pending_review(self):
        su = User.objects.create_superuser('root', 'r@x.com', 'pw')
        c = Client(); c.force_login(su)
        Client().post('/accounts/register/', reg_post())
        resp = c.get('/accounts/admin-panel/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Pending Review')
        self.assertNotContains(resp, 'Approve &amp; Activate')
        self.assertContains(resp, 'Registered Clinics')
        self.assertContains(resp, 'activated instantly')
        self.assertContains(resp, 'Live since')

    def test_legacy_pending_registrations_activated_by_command(self):
        from django.contrib.auth.hashers import make_password
        ClinicRegistrationRequest.objects.create(
            clinic_name='Old Pending Clinic', clinic_type=ClinicRegistrationRequest.CLINIC_TYPES[0][0],
            city='Pune', state='Maharashtra', clinic_phone='020111', doctor_name='Dr. Old',
            phone='9111111111', email='old@example.com', password_hash=make_password('OldPass123'),
            status='pending',
        )
        call_command('activate_pending_registrations', stdout=open('/dev/null', 'w'))
        call_command('activate_pending_registrations', stdout=open('/dev/null', 'w'))   # idempotent
        self.assertEqual(ClinicRegistrationRequest.objects.get(phone='9111111111').status, 'approved')
        self.assertEqual(Clinic.objects.filter(name='Old Pending Clinic').count(), 1)
        self.assertTrue(Client().login(username='9111111111', password='OldPass123'))

    def test_legacy_pending_with_taken_mobile_is_skipped(self):
        from django.contrib.auth.hashers import make_password
        User.objects.create_user('9222222222', password='x')
        ClinicRegistrationRequest.objects.create(
            clinic_name='Clash', clinic_type=ClinicRegistrationRequest.CLINIC_TYPES[0][0], city='Pune',
            state='MH', clinic_phone='1', doctor_name='Dr. C', phone='9222222222', email='c@example.com',
            password_hash=make_password('x'), status='pending',
        )
        call_command('activate_pending_registrations', stdout=open('/dev/null', 'w'))
        self.assertEqual(ClinicRegistrationRequest.objects.get(phone='9222222222').status, 'pending')
        self.assertFalse(Clinic.objects.filter(name='Clash').exists())


class FirstLoginTourTest(TestCase):

    def make_staff(self, role, tour_completed=False, username='u1'):
        clinic = Clinic.objects.create(name='Tour Clinic', city='Delhi')
        user = User.objects.create_user(username, password='pw')
        sm = StaffMember.objects.create(clinic=clinic, user=user, role=role, display_name='Dr. Tour',
                                        tour_completed=tour_completed)
        set_permissions_from_role(sm)
        sm.save()
        c = Client(); c.force_login(user)
        return sm, c

    def test_new_admin_gets_tour(self):
        sm, c = self.make_staff('admin')
        resp = c.get('/')
        self.assertTrue(resp.context['show_tour'])
        self.assertContains(resp, 'id="ct-root"')
        self.assertContains(resp, 'const AUTO = true;')
        self.assertContains(resp, 'Ask the AI assistant anything')

    def test_new_doctor_gets_tour(self):
        sm, c = self.make_staff('doctor')
        self.assertTrue(c.get('/').context['show_tour'])

    def test_receptionist_does_not_auto_start(self):
        sm, c = self.make_staff('receptionist')
        resp = c.get('/')
        self.assertFalse(resp.context['show_tour'])
        self.assertContains(resp, 'const AUTO = false;')
        self.assertContains(resp, 'Take the tour')        # still replayable

    def test_completed_tour_not_shown_again(self):
        sm, c = self.make_staff('admin', tour_completed=True)
        resp = c.get('/')
        self.assertFalse(resp.context['show_tour'])
        self.assertContains(resp, 'const AUTO = false;')

    def test_complete_api_marks_done(self):
        sm, c = self.make_staff('admin')
        resp = c.post('/accounts/api/tour/complete/')
        self.assertEqual(resp.json(), {'ok': True})
        sm.refresh_from_db()
        self.assertTrue(sm.tour_completed)
        self.assertFalse(c.get('/').context['show_tour'])

    def test_complete_api_requires_post_and_login(self):
        sm, c = self.make_staff('admin')
        self.assertEqual(c.get('/accounts/api/tour/complete/').status_code, 405)
        self.assertEqual(Client().post('/accounts/api/tour/complete/').status_code, 302)

    def test_tour_targets_present_on_dashboard(self):
        sm, c = self.make_staff('admin')
        html = c.get('/').content.decode()
        for target in ('id="help-wrap"', 'data-tour="patients"', 'data-tour="stats"', 'data-tour="queue"',
                       'data-tour="walkin"', 'data-tour="nav-doctor"', 'data-tour="nav-pharmacy"',
                       'data-tour="nav-staff"', 'id="nav-hamburger"'):
            self.assertIn(target, html)

    def test_doctor_name_is_escaped(self):
        sm, c = self.make_staff('admin')
        sm.display_name = 'Dr. <img src=x onerror=alert(1)>'
        sm.save()
        html = c.get('/').content.decode()
        self.assertNotIn('<img src=x onerror=alert(1)>', html)

    def test_existing_staff_marked_done_by_migration_sql(self):
        """Migration: existing rows → TRUE, new rows default FALSE; re-running is harmless."""
        mod = importlib.import_module('accounts.migrations.0023_staffmember_tour_completed')
        with connection.cursor() as cur:
            cur.execute(mod.Migration.operations[0].sql)   # re-run (idempotent)
            cur.execute("SELECT column_default FROM information_schema.columns "
                        "WHERE table_name='accounts_staffmember' AND column_name='tour_completed'")
            self.assertEqual(cur.fetchone()[0], 'false')
