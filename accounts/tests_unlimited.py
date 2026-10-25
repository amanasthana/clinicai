"""Unlimited AI prescriptions for selected clinics (lifetime gift), granted from the admin panel."""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role


def _clinic(name):
    return Clinic.objects.create(name=name, address='1 Rd', city='Pune', phone='9000000000')


def _staff(user, clinic, role='doctor'):
    sm = StaffMember.objects.create(user=user, clinic=clinic, role=role, display_name=user.username)
    set_permissions_from_role(sm)
    sm.save()
    return sm


@override_settings(FREE_DAILY_RX_LIMIT=0)   # every clinic is "at the limit" unless unlimited
class DailyLimitTest(TestCase):
    def setUp(self):
        self.clinic = _clinic('Rajeev Skin Care')
        self.user = User.objects.create_user('dr_rajeev', password='pass12345')
        _staff(self.user, self.clinic)
        self.client = Client()
        self.client.login(username='dr_rajeev', password='pass12345')

    def generate(self):
        return self.client.post('/rx/generate/', json.dumps({'clinical_note': ''}),
                                content_type='application/json')

    def test_limited_clinic_is_blocked(self):
        resp = self.generate()
        self.assertEqual(resp.status_code, 429)
        self.assertTrue(resp.json()['limit_reached'])

    def test_unlimited_clinic_is_not_blocked(self):
        self.clinic.unlimited_prescriptions = True
        self.clinic.save()
        resp = self.generate()
        self.assertNotEqual(resp.status_code, 429)
        self.assertFalse(resp.json().get('limit_reached', False))

    def test_plan_page_shows_unlimited(self):
        self.clinic.unlimited_prescriptions = True
        self.clinic.save()
        resp = self.client.get('/accounts/plan/')
        self.assertContains(resp, 'Unlimited AI prescriptions')
        self.assertNotContains(resp, 'Request Pro Upgrade')

    def test_plan_page_limited(self):
        resp = self.client.get('/accounts/plan/')
        self.assertContains(resp, 'Request Pro Upgrade')


class AdminGrantTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', password='pass12345')
        self.rajeev = _clinic('Rajeev Skin Care')
        self.branch = _clinic('Rajeev Skin Care Branch 2')
        self.other = _clinic('Someone Else Clinic')
        dr = User.objects.create_user('9811111111', password='pass12345')
        _staff(dr, self.rajeev)
        _staff(dr, self.branch, role='admin')
        recep = User.objects.create_user('recep', password='pass12345')
        _staff(recep, self.rajeev, role='receptionist')
        _staff(recep, self.other, role='receptionist')   # shared receptionist does not link clinics
        self.client = Client()
        self.client.login(username='boss', password='pass12345')

    def grant(self, clinic, enable='1', include_linked='1'):
        data = {'enable': enable}
        if include_linked:
            data['include_linked'] = include_linked
        return self.client.post(f'/accounts/admin-panel/clinic/{clinic.pk}/unlimited/', data)

    def test_linked_clinics(self):
        self.assertEqual(list(self.rajeev.linked_clinics()), [self.branch])

    def test_grant_with_linked(self):
        self.assertEqual(self.grant(self.rajeev).status_code, 302)
        self.assertEqual(
            set(Clinic.objects.filter(unlimited_prescriptions=True).values_list('name', flat=True)),
            {'Rajeev Skin Care', 'Rajeev Skin Care Branch 2'})

    def test_grant_only_this_clinic(self):
        self.grant(self.rajeev, include_linked='')
        self.assertEqual(list(Clinic.objects.filter(unlimited_prescriptions=True)), [self.rajeev])

    def test_remove(self):
        self.grant(self.rajeev)
        self.grant(self.rajeev, enable='0')
        self.assertFalse(Clinic.objects.filter(unlimited_prescriptions=True).exists())

    def test_admin_panel_shows_controls(self):
        resp = self.client.get('/accounts/admin-panel/')
        self.assertContains(resp, 'Give unlimited Rx')
        self.assertContains(resp, '+ 1 linked')

    def test_non_superuser_forbidden(self):
        User.objects.create_user('nobody', password='pass12345')
        c = Client()
        c.login(username='nobody', password='pass12345')
        resp = c.post(f'/accounts/admin-panel/clinic/{self.rajeev.pk}/unlimited/', {'enable': '1'})
        self.assertEqual(resp.status_code, 403)
        self.rajeev.refresh_from_db()
        self.assertFalse(self.rajeev.unlimited_prescriptions)
