from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings

from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role
from notifications.models import EmailCampaignSend


def _clinic(name, unlimited=False):
    return Clinic.objects.create(name=name, address='1 Rd', city='Pune', phone='9000000000',
                                 unlimited_prescriptions=unlimited)


def _staff(username, email, clinic, role='doctor'):
    user, _ = User.objects.get_or_create(username=username, defaults={'email': email})
    sm = StaffMember.objects.create(user=user, clinic=clinic, role=role, display_name=username)
    set_permissions_from_role(sm)
    sm.save()
    return user


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_ALLOWED_RECIPIENTS=[])
class GiftEmailTest(TestCase):
    def setUp(self):
        self.rajeev = _clinic('Rajeev Skin Care', unlimited=True)
        self.branch = _clinic('Rajeev Skin Care Branch', unlimited=True)
        self.other = _clinic('Other Clinic', unlimited=True)
        _staff('dr_rajeev', 'Rajeev@Example.com', self.rajeev)
        _staff('dr_rajeev', 'Rajeev@Example.com', self.branch, role='admin')   # same doctor, linked clinic
        _staff('recep', 'recep@example.com', self.rajeev, role='receptionist')  # not a doctor/admin
        _staff('dr_noemail', '', self.rajeev)
        _staff('dr_other', 'other@example.com', self.other)
        User.objects.create_superuser('boss', email='boss@example.com', password='pass12345')
        self.client = Client()
        self.client.login(username='boss', password='pass12345')
        self.url = f'/notifications/gift/{self.rajeev.pk}/'

    def test_page_lists_only_the_clinic_doctors(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r['email'] for r in resp.context['rows']], ['rajeev@example.com'])
        self.assertEqual(resp.context['rows'][0]['clinics'], ['Rajeev Skin Care', 'Rajeev Skin Care Branch'])

    def test_test_send_goes_only_to_me_and_is_not_recorded(self):
        self.client.post(self.url, {'action': 'test', 'test_email': 'me@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['me@example.com'])
        self.assertIn('lifetime', mail.outbox[0].subject.lower())
        self.assertIn('unlimited prescriptions per day', mail.outbox[0].body)
        self.assertFalse(EmailCampaignSend.objects.exists())

    def test_send_to_clinic_once(self):
        self.client.post(self.url, {'action': 'send'})
        self.assertEqual([m.to for m in mail.outbox], [['rajeev@example.com']])
        self.client.post(self.url, {'action': 'send'})
        self.client.post(f'/notifications/gift/{self.branch.pk}/', {'action': 'send'})
        self.assertEqual(len(mail.outbox), 1)   # never twice, from any linked clinic page

    def test_not_sent_when_unlimited_is_off(self):
        Clinic.objects.update(unlimited_prescriptions=False)
        self.client.post(self.url, {'action': 'send'})
        self.assertEqual(len(mail.outbox), 0)

    def test_preview(self):
        resp = self.client.get(self.url + 'preview/')
        self.assertContains(resp, 'Dear Sir')
        self.assertContains(resp, 'Rajeev Skin Care Branch')

    def test_admin_panel_links_to_page(self):
        self.assertContains(self.client.get('/accounts/admin-panel/'), self.url)

    def test_non_superuser_forbidden(self):
        c = Client()
        c.force_login(User.objects.get(username='dr_rajeev'))
        self.assertEqual(c.post(self.url, {'action': 'send'}).status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
