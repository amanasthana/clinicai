"""
Comprehensive tests for the pharmacy app after the PharmacyItem + PharmacyBatch refactor.
"""

import datetime
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from pharmacy.models import MedicineCatalog, PharmacyItem, PharmacyBatch, DoctorFavorite
from accounts.models import Clinic, StaffMember


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_clinic_and_user(username='testdoctor', clinic_name='Test Clinic'):
    """Create a Clinic + User + StaffMember (admin role) and return (clinic, user, staff)."""
    clinic = Clinic.objects.create(
        name=clinic_name,
        address='123 Test St',
        city='Mumbai',
        phone='9000000001',
    )
    user = User.objects.create_user(username=username, password='testpass123')
    staff = StaffMember.objects.create(
        clinic=clinic,
        user=user,
        role='admin',
        display_name='Test Doctor',
    )
    return clinic, user, staff


def make_catalog_medicine(name='Paracetamol', generic='Acetaminophen'):
    return MedicineCatalog.objects.create(
        name=name,
        generic_name=generic,
        form='Tab',
        manufacturer='ABC Pharma',
        category='Analgesic',
    )


def today():
    return timezone.now().date()


# ---------------------------------------------------------------------------
# Model tests — PharmacyItem
# ---------------------------------------------------------------------------

class PharmacyItemModelTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user()
        self.med = make_catalog_medicine()
        self.item = PharmacyItem.objects.create(
            clinic=self.clinic,
            medicine=self.med,
            reorder_level=10,
        )

    def _make_batch(self, qty, expiry_offset_days=None, batch_number='B001'):
        expiry = None
        if expiry_offset_days is not None:
            expiry = today() + datetime.timedelta(days=expiry_offset_days)
        return PharmacyBatch.objects.create(
            item=self.item,
            batch_number=batch_number,
            expiry_date=expiry,
            quantity=qty,
            unit_price=5,
        )

    # --- total_quantity ---

    def test_total_quantity_no_batches(self):
        self.assertEqual(self.item.total_quantity, 0)

    def test_total_quantity_sums_all_batches(self):
        self._make_batch(20, batch_number='B001')
        self._make_batch(30, batch_number='B002')
        self.assertEqual(self.item.total_quantity, 50)

    def test_total_quantity_with_zero_qty_batch(self):
        self._make_batch(15, batch_number='B001')
        self._make_batch(0, batch_number='B002')
        self.assertEqual(self.item.total_quantity, 15)

    # --- in_stock ---

    def test_in_stock_false_when_no_batches(self):
        self.assertFalse(self.item.in_stock)

    def test_in_stock_true_when_quantity_exists(self):
        self._make_batch(1)
        self.assertTrue(self.item.in_stock)

    def test_in_stock_false_when_all_batches_empty(self):
        self._make_batch(0, batch_number='B001')
        self._make_batch(0, batch_number='B002')
        self.assertFalse(self.item.in_stock)

    # --- low_stock ---

    def test_low_stock_true_when_below_reorder_level(self):
        self._make_batch(5)  # reorder_level = 10
        self.assertTrue(self.item.low_stock)

    def test_low_stock_true_at_reorder_level(self):
        self._make_batch(10)  # exactly at reorder_level
        self.assertTrue(self.item.low_stock)

    def test_low_stock_false_above_reorder_level(self):
        self._make_batch(20)
        self.assertFalse(self.item.low_stock)

    def test_low_stock_false_when_out_of_stock(self):
        # 0 quantity -> in_stock=False, so low_stock must be False too
        self.assertFalse(self.item.low_stock)

    # --- earliest_expiry ---

    def test_earliest_expiry_none_when_no_batches(self):
        self.assertIsNone(self.item.earliest_expiry)

    def test_earliest_expiry_returns_soonest_batch_with_stock(self):
        self._make_batch(10, expiry_offset_days=90, batch_number='B001')
        self._make_batch(10, expiry_offset_days=30, batch_number='B002')
        expected = today() + datetime.timedelta(days=30)
        self.assertEqual(self.item.earliest_expiry, expected)

    def test_earliest_expiry_skips_empty_batches(self):
        self._make_batch(0, expiry_offset_days=10, batch_number='B001')  # empty, skip
        self._make_batch(5, expiry_offset_days=90, batch_number='B002')
        expected = today() + datetime.timedelta(days=90)
        self.assertEqual(self.item.earliest_expiry, expected)

    def test_earliest_expiry_none_when_all_batches_have_no_expiry(self):
        PharmacyBatch.objects.create(item=self.item, quantity=10, unit_price=5)
        self.assertIsNone(self.item.earliest_expiry)

    # --- use_first_batch (FEFO) ---

    def test_use_first_batch_returns_soonest_expiry_batch(self):
        b1 = self._make_batch(10, expiry_offset_days=90, batch_number='B001')
        b2 = self._make_batch(10, expiry_offset_days=30, batch_number='B002')
        self.assertEqual(self.item.use_first_batch.pk, b2.pk)

    def test_use_first_batch_skips_empty_batches(self):
        self._make_batch(0, expiry_offset_days=10, batch_number='B001')
        stocked = self._make_batch(5, expiry_offset_days=90, batch_number='B002')
        self.assertEqual(self.item.use_first_batch.pk, stocked.pk)

    def test_use_first_batch_none_when_no_stocked_batches_with_expiry(self):
        PharmacyBatch.objects.create(item=self.item, quantity=10, unit_price=5)  # no expiry
        self.assertIsNone(self.item.use_first_batch)

    # --- display_name ---

    def test_display_name_uses_medicine_name(self):
        self.assertEqual(self.item.display_name, self.med.name)

    def test_display_name_uses_custom_name_when_no_medicine(self):
        item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Custom Herb X',
            reorder_level=5,
        )
        self.assertEqual(item.display_name, 'Custom Herb X')

    def test_str_returns_display_name(self):
        self.assertEqual(str(self.item), self.med.name)


# ---------------------------------------------------------------------------
# Model tests — PharmacyBatch
# ---------------------------------------------------------------------------

class PharmacyBatchModelTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user()
        self.med = make_catalog_medicine()
        self.item = PharmacyItem.objects.create(
            clinic=self.clinic,
            medicine=self.med,
            reorder_level=10,
        )

    def _make_batch(self, expiry_offset_days=None, qty=10):
        expiry = None
        if expiry_offset_days is not None:
            expiry = today() + datetime.timedelta(days=expiry_offset_days)
        return PharmacyBatch.objects.create(
            item=self.item,
            expiry_date=expiry,
            quantity=qty,
            unit_price=5,
        )

    # --- is_near_expiry ---

    def test_is_near_expiry_false_when_no_expiry(self):
        batch = self._make_batch()
        self.assertFalse(batch.is_near_expiry)

    def test_is_near_expiry_true_when_within_60_days(self):
        batch = self._make_batch(expiry_offset_days=59)
        self.assertTrue(batch.is_near_expiry)

    def test_is_near_expiry_true_at_exactly_60_days(self):
        batch = self._make_batch(expiry_offset_days=60)
        self.assertTrue(batch.is_near_expiry)

    def test_is_near_expiry_false_when_beyond_60_days(self):
        batch = self._make_batch(expiry_offset_days=61)
        self.assertFalse(batch.is_near_expiry)

    # --- is_expired ---

    def test_is_expired_false_when_no_expiry(self):
        batch = self._make_batch()
        self.assertFalse(batch.is_expired)

    def test_is_expired_false_when_future(self):
        batch = self._make_batch(expiry_offset_days=10)
        self.assertFalse(batch.is_expired)

    def test_is_expired_true_when_in_past(self):
        batch = self._make_batch(expiry_offset_days=-1)
        self.assertTrue(batch.is_expired)

    # --- ordering (FEFO) ---

    def test_batches_ordered_by_expiry_ascending(self):
        b_far = self._make_batch(expiry_offset_days=180)
        b_near = self._make_batch(expiry_offset_days=30)
        b_mid = self._make_batch(expiry_offset_days=90)
        ordered = list(PharmacyBatch.objects.filter(item=self.item))
        self.assertEqual(ordered[0].pk, b_near.pk)
        self.assertEqual(ordered[1].pk, b_mid.pk)
        self.assertEqual(ordered[2].pk, b_far.pk)

    # --- str ---

    def test_str_includes_medicine_name_and_batch_number(self):
        batch = PharmacyBatch.objects.create(
            item=self.item,
            batch_number='XYZ-99',
            quantity=10,
            unit_price=5,
        )
        self.assertIn('Paracetamol', str(batch))
        self.assertIn('XYZ-99', str(batch))


# ---------------------------------------------------------------------------
# View tests
# ---------------------------------------------------------------------------

class PharmacyViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user()
        self.client = Client()
        self.client.login(username='testdoctor', password='testpass123')

        self.med = make_catalog_medicine()
        self.item = PharmacyItem.objects.create(
            clinic=self.clinic,
            medicine=self.med,
            reorder_level=10,
        )
        self.batch = PharmacyBatch.objects.create(
            item=self.item,
            batch_number='BATCH001',
            expiry_date=today() + datetime.timedelta(days=180),
            quantity=50,
            unit_price='10.00',
        )

    # --- dashboard ---

    def test_dashboard_loads(self):
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_contains_item(self):
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'Paracetamol')

    def test_dashboard_shows_correct_total_quantity(self):
        resp = self.client.get('/pharmacy/')
        items = list(resp.context['items'])
        item_obj = next(i for i in items if i.pk == self.item.pk)
        self.assertEqual(item_obj.total_quantity, 50)

    def test_dashboard_total_in_stock_count(self):
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.context['total_in_stock'], 1)

    # --- add_stock -- new medicine + batch ---

    def test_add_stock_creates_new_item_and_batch(self):
        med2 = make_catalog_medicine(name='Metformin', generic='Metformin HCl')
        pre_items = PharmacyItem.objects.filter(clinic=self.clinic).count()
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': med2.pk,
            'batch_number': 'MET001',
            'expiry_date': str(today() + datetime.timedelta(days=365)),
            'quantity': 100,
            'unit_price': '2.50',
            'reorder_level': 20,
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.assertEqual(PharmacyItem.objects.filter(clinic=self.clinic).count(), pre_items + 1)
        new_item = PharmacyItem.objects.get(clinic=self.clinic, medicine=med2)
        self.assertEqual(new_item.batches.count(), 1)
        batch = new_item.batches.first()
        self.assertEqual(batch.batch_number, 'MET001')
        self.assertEqual(batch.quantity, 100)

    def test_add_stock_to_existing_medicine_adds_batch(self):
        """POSTing add_stock for an already-existing medicine should add a batch, not a new item."""
        pre_items = PharmacyItem.objects.filter(clinic=self.clinic).count()
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': self.med.pk,
            'batch_number': 'BATCH002',
            'expiry_date': str(today() + datetime.timedelta(days=200)),
            'quantity': 25,
            'unit_price': '10.00',
            'reorder_level': 10,
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.assertEqual(PharmacyItem.objects.filter(clinic=self.clinic).count(), pre_items)
        self.item.refresh_from_db()
        self.assertEqual(self.item.batches.count(), 2)

    def test_add_stock_custom_name_creates_item(self):
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': '',
            'custom_name': 'Neem Extract',
            'batch_number': '',
            'expiry_date': '',
            'quantity': 5,
            'unit_price': '0',
            'reorder_level': 5,
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.assertTrue(PharmacyItem.objects.filter(clinic=self.clinic, custom_name='Neem Extract').exists())

    def test_add_stock_no_medicine_returns_error(self):
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': '',
            'custom_name': '',
            'quantity': 10,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Please select a medicine')

    # --- add_batch view ---

    def test_add_batch_adds_batch_to_existing_item(self):
        pre_batch_count = self.item.batches.count()
        resp = self.client.post(f'/pharmacy/item/{self.item.pk}/add-batch/', {
            'batch_number': 'NEW-BATCH',
            'expiry_date': str(today() + datetime.timedelta(days=300)),
            'quantity': 75,
            'unit_price': '12.00',
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.assertEqual(self.item.batches.count(), pre_batch_count + 1)
        new_batch = self.item.batches.order_by('-id').first()
        self.assertEqual(new_batch.batch_number, 'NEW-BATCH')
        self.assertEqual(new_batch.quantity, 75)

    def test_add_batch_get_shows_form(self):
        resp = self.client.get(f'/pharmacy/item/{self.item.pk}/add-batch/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Paracetamol')

    # --- edit_batch view ---

    def test_edit_batch_updates_fields(self):
        resp = self.client.post(f'/pharmacy/batch/{self.batch.pk}/edit/', {
            'batch_number': 'EDITED-BATCH',
            'expiry_date': str(today() + datetime.timedelta(days=90)),
            'quantity': 30,
            'unit_price': '15.00',
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.batch_number, 'EDITED-BATCH')
        self.assertEqual(self.batch.quantity, 30)

    def test_edit_batch_get_shows_form(self):
        resp = self.client.get(f'/pharmacy/batch/{self.batch.pk}/edit/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'BATCH001')

    # --- delete_batch ---

    def test_delete_batch_removes_batch(self):
        batch2 = PharmacyBatch.objects.create(
            item=self.item,
            batch_number='TEMP',
            quantity=5,
            unit_price=1,
        )
        resp = self.client.post(f'/pharmacy/batch/{batch2.pk}/delete/')
        self.assertRedirects(resp, '/pharmacy/')
        self.assertFalse(PharmacyBatch.objects.filter(pk=batch2.pk).exists())

    def test_delete_last_batch_also_removes_item(self):
        """When the last batch is deleted the PharmacyItem should be cleaned up too."""
        resp = self.client.post(f'/pharmacy/batch/{self.batch.pk}/delete/')
        self.assertRedirects(resp, '/pharmacy/')
        self.assertFalse(PharmacyItem.objects.filter(pk=self.item.pk).exists())

    # --- delete_item ---

    def test_delete_item_removes_item_and_batches(self):
        resp = self.client.post(f'/pharmacy/item/{self.item.pk}/delete/')
        self.assertRedirects(resp, '/pharmacy/')
        self.assertFalse(PharmacyItem.objects.filter(pk=self.item.pk).exists())
        self.assertFalse(PharmacyBatch.objects.filter(item=self.item).exists())

    # --- flag_reorder ---

    def test_flag_reorder_toggles_flag(self):
        self.assertFalse(self.item.reorder_flagged)
        self.client.post(f'/pharmacy/item/{self.item.pk}/flag/')
        self.item.refresh_from_db()
        self.assertTrue(self.item.reorder_flagged)
        self.client.post(f'/pharmacy/item/{self.item.pk}/flag/')
        self.item.refresh_from_db()
        self.assertFalse(self.item.reorder_flagged)

    # --- pharmacy_search_api (pharmacy app's own) ---

    def test_pharmacy_search_api_returns_total_quantity(self):
        # Add a second batch
        PharmacyBatch.objects.create(item=self.item, quantity=20, unit_price=5)
        resp = self.client.get('/pharmacy/api/search/?q=Para')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('items', data)
        match = next((i for i in data['items'] if 'Paracetamol' in i['name']), None)
        self.assertIsNotNone(match)
        # total_quantity = 50 (original batch) + 20 (new batch)
        self.assertEqual(match['quantity'], 70)
        self.assertTrue(match['in_stock'])

    def test_pharmacy_search_api_empty_query_returns_empty(self):
        resp = self.client.get('/pharmacy/api/search/?q=')
        data = resp.json()
        self.assertEqual(data['items'], [])

    # --- catalog_search_api ---

    def test_catalog_search_api_returns_catalog_items(self):
        resp = self.client.get('/pharmacy/api/catalog/?q=Para')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('items', data)
        names = [i['name'] for i in data['items']]
        self.assertIn('Paracetamol', names)

    def test_catalog_search_api_short_query_returns_empty(self):
        resp = self.client.get('/pharmacy/api/catalog/?q=P')
        data = resp.json()
        self.assertEqual(data['items'], [])

    # --- cross-clinic isolation ---

    def test_dashboard_only_shows_own_clinic_items(self):
        other_clinic, other_user, _ = make_clinic_and_user(username='otherdoc', clinic_name='Other Clinic')
        other_med = make_catalog_medicine(name='Ibuprofen', generic='Ibuprofen')
        other_item = PharmacyItem.objects.create(clinic=other_clinic, medicine=other_med, reorder_level=5)
        PharmacyBatch.objects.create(item=other_item, quantity=10, unit_price=5)

        resp = self.client.get('/pharmacy/')
        items = list(resp.context['items'])
        item_clinics = {i.clinic_id for i in items}
        self.assertNotIn(other_clinic.pk, item_clinics)
