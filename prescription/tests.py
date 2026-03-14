"""Tests for prescription feature: brand search in pharmacy typeahead, and medical term suggest API."""
import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from pharmacy.models import MedicineCatalog, PharmacyItem, PharmacyBatch
from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role


def make_clinic_and_user(username='rxtest', clinic_name='RX Test Clinic'):
    clinic = Clinic.objects.create(name=clinic_name, address='1 Test', city='Mumbai', phone='9100000001')
    user = User.objects.create_user(username=username, password='testpass')
    sm = StaffMember.objects.create(clinic=clinic, user=user, role='admin', display_name='Test Doctor')
    set_permissions_from_role(sm)
    sm.save()
    return clinic, user


class PharmacySearchAPITest(TestCase):
    """Tests for /rx/api/pharmacy-search/ used by brand typeahead in prescription."""

    def setUp(self):
        self.clinic, self.user = make_clinic_and_user()
        self.client = Client()
        self.client.login(username='rxtest', password='testpass')
        # Create a catalog medicine
        self.med = MedicineCatalog.objects.create(
            name='Pantocid', generic_name='Pantoprazole', form='Tab', manufacturer='Sun Pharma', category='GI'
        )
        self.item = PharmacyItem.objects.create(clinic=self.clinic, medicine=self.med, reorder_level=5)
        self.batch = PharmacyBatch.objects.create(
            item=self.item, quantity=24,
            expiry_date=__import__('datetime').date(2027, 6, 1)
        )

    def test_search_by_brand_name_finds_item(self):
        resp = self.client.get('/rx/api/pharmacy-search/?q=Pantocid')
        data = resp.json()
        names = [r['name'] for r in data['results']]
        self.assertIn('Pantocid', names)

    def test_search_by_generic_name_finds_brand(self):
        resp = self.client.get('/rx/api/pharmacy-search/?q=Pantoprazole')
        data = resp.json()
        names = [r['name'] for r in data['results']]
        self.assertIn('Pantocid', names)

    def test_search_returns_expiry_field(self):
        resp = self.client.get('/rx/api/pharmacy-search/?q=Pantocid')
        data = resp.json()
        item = next((r for r in data['results'] if r['name'] == 'Pantocid'), None)
        self.assertIsNotNone(item)
        self.assertIn('expiry', item)
        self.assertEqual(item['expiry'], 'Jun 2027')

    def test_search_returns_generic_field(self):
        resp = self.client.get('/rx/api/pharmacy-search/?q=Pantocid')
        data = resp.json()
        item = next((r for r in data['results'] if r['name'] == 'Pantocid'), None)
        self.assertIsNotNone(item)
        self.assertEqual(item['generic'], 'Pantoprazole')

    def test_search_returns_availability_ok(self):
        resp = self.client.get('/rx/api/pharmacy-search/?q=Pantocid')
        data = resp.json()
        item = next((r for r in data['results'] if r['name'] == 'Pantocid'), None)
        self.assertEqual(item['availability'], 'ok')

    def test_search_returns_availability_low(self):
        self.item.reorder_level = 30  # batch has 24 units → low
        self.item.save()
        resp = self.client.get('/rx/api/pharmacy-search/?q=Pantocid')
        data = resp.json()
        item = next((r for r in data['results'] if r['name'] == 'Pantocid'), None)
        self.assertEqual(item['availability'], 'low')

    def test_search_returns_availability_out(self):
        self.batch.quantity = 0
        self.batch.save()
        resp = self.client.get('/rx/api/pharmacy-search/?q=Pantocid')
        data = resp.json()
        item = next((r for r in data['results'] if r['name'] == 'Pantocid'), None)
        self.assertEqual(item['availability'], 'out')

    def test_search_by_custom_generic_name(self):
        custom_item = PharmacyItem.objects.create(
            clinic=self.clinic, custom_name='Clinico Oint', custom_generic_name='Clindamycin 1%', reorder_level=5
        )
        PharmacyBatch.objects.create(item=custom_item, quantity=10)
        resp = self.client.get('/rx/api/pharmacy-search/?q=Clindamycin')
        data = resp.json()
        names = [r['name'] for r in data['results']]
        self.assertIn('Clinico Oint', names)

    def test_search_short_query_returns_empty(self):
        resp = self.client.get('/rx/api/pharmacy-search/?q=P')
        data = resp.json()
        self.assertEqual(data['results'], [])

    def test_search_requires_login(self):
        anon = Client()
        resp = anon.get('/rx/api/pharmacy-search/?q=Pantocid')
        self.assertIn(resp.status_code, [302, 403])

    def test_cross_clinic_isolation(self):
        other_clinic, other_user = make_clinic_and_user('other_rx', 'Other Clinic')
        other_med = MedicineCatalog.objects.create(
            name='OtherDrug', generic_name='SecretGeneric', form='Tab', manufacturer='X', category='Y'
        )
        other_item = PharmacyItem.objects.create(clinic=other_clinic, medicine=other_med, reorder_level=5)
        PharmacyBatch.objects.create(item=other_item, quantity=10)
        resp = self.client.get('/rx/api/pharmacy-search/?q=SecretGeneric')
        data = resp.json()
        names = [r['name'] for r in data['results']]
        self.assertNotIn('OtherDrug', names)


class MedicalTermSuggestTest(TestCase):
    """Tests for the suggest_terms API and new clinical phrase terms."""

    def setUp(self):
        self.clinic, self.user = make_clinic_and_user('termtest', 'Term Clinic')
        self.client = Client()
        self.client.login(username='termtest', password='testpass')
        # Create some specific terms
        from prescription.models import MedicalTerm
        MedicalTerm.objects.create(term='Fever since 3 days', category='snippet', aliases='fever 3 days bukhar', weight=88)
        MedicalTerm.objects.create(term='Abdomen soft, non-tender', category='snippet', aliases='soft abdomen non tender', weight=87)
        MedicalTerm.objects.create(term='Type 2 Diabetes Mellitus', category='diagnosis', aliases='T2DM diabetes type 2', weight=90, icd_code='E11')
        MedicalTerm.objects.create(term='Undergoing chemotherapy — cycle [X]', category='snippet', aliases='on chemotherapy cycle', weight=87)
        MedicalTerm.objects.create(term='Essential Hypertension', category='diagnosis', aliases='primary hypertension HTN', weight=90, icd_code='I10')

    def test_suggest_finds_fever_phrase(self):
        resp = self.client.get('/rx/api/suggest/?q=fever')
        data = resp.json()
        terms = [r['term'] for r in data['results']]
        self.assertIn('Fever since 3 days', terms)

    def test_suggest_finds_abdomen_phrase(self):
        resp = self.client.get('/rx/api/suggest/?q=abd')
        data = resp.json()
        terms = [r['term'] for r in data['results']]
        self.assertIn('Abdomen soft, non-tender', terms)

    def test_suggest_finds_diabetes_comorbidity(self):
        resp = self.client.get('/rx/api/suggest/?q=diab')
        data = resp.json()
        terms = [r['term'] for r in data['results']]
        self.assertIn('Type 2 Diabetes Mellitus', terms)

    def test_suggest_finds_chemo_history(self):
        resp = self.client.get('/rx/api/suggest/?q=chemo')
        data = resp.json()
        terms = [r['term'] for r in data['results']]
        self.assertIn('Undergoing chemotherapy — cycle [X]', terms)

    def test_suggest_finds_by_alias(self):
        # searching "T2DM" should find "Type 2 Diabetes Mellitus" via aliases
        resp = self.client.get('/rx/api/suggest/?q=T2DM')
        data = resp.json()
        terms = [r['term'] for r in data['results']]
        self.assertIn('Type 2 Diabetes Mellitus', terms)

    def test_suggest_returns_category_field(self):
        resp = self.client.get('/rx/api/suggest/?q=hyper')
        data = resp.json()
        self.assertTrue(len(data['results']) > 0)
        for r in data['results']:
            self.assertIn('category', r)

    def test_suggest_short_query_returns_empty(self):
        resp = self.client.get('/rx/api/suggest/?q=f')
        data = resp.json()
        self.assertEqual(data['results'], [])

    def test_suggest_requires_login(self):
        anon = Client()
        resp = anon.get('/rx/api/suggest/?q=fever')
        self.assertIn(resp.status_code, [302, 403])
