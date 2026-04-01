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
from accounts.permissions import set_permissions_from_role


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
    set_permissions_from_role(staff)
    staff.save()
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

    def test_is_near_expiry_true_when_within_90_days(self):
        batch = self._make_batch(expiry_offset_days=59)
        self.assertTrue(batch.is_near_expiry)

    def test_is_near_expiry_true_at_exactly_90_days(self):
        batch = self._make_batch(expiry_offset_days=90)
        self.assertTrue(batch.is_near_expiry)

    def test_is_near_expiry_false_when_beyond_90_days(self):
        batch = self._make_batch(expiry_offset_days=91)
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
            'unit_price': '8.00',
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


# ---------------------------------------------------------------------------
# Custom generic name tests (Feature: generic composition for custom medicines)
# ---------------------------------------------------------------------------

class CustomGenericNameModelTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user(username='gentest', clinic_name='Gen Clinic')

    def test_pharmacy_item_has_custom_generic_name_field(self):
        item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Clinico Ointment',
            custom_generic_name='Clindamycin 1% w/w',
            reorder_level=5,
        )
        item.refresh_from_db()
        self.assertEqual(item.custom_generic_name, 'Clindamycin 1% w/w')

    def test_display_generic_returns_custom_generic_name_for_custom_item(self):
        item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Clinico Ointment',
            custom_generic_name='Clindamycin 1% w/w',
            reorder_level=5,
        )
        self.assertEqual(item.display_generic, 'Clindamycin 1% w/w')

    def test_display_generic_returns_catalog_generic_for_catalog_item(self):
        med = make_catalog_medicine(name='Crocin', generic='Paracetamol 500mg')
        item = PharmacyItem.objects.create(clinic=self.clinic, medicine=med, reorder_level=5)
        self.assertEqual(item.display_generic, 'Paracetamol 500mg')

    def test_display_generic_blank_for_custom_item_without_generic(self):
        item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Mystery Tonic',
            reorder_level=5,
        )
        self.assertEqual(item.display_generic, '')

    def test_custom_generic_name_default_blank(self):
        item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Plain Med',
            reorder_level=5,
        )
        self.assertEqual(item.custom_generic_name, '')


class AddStockCustomGenericViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user(username='stocktest', clinic_name='Stock Clinic')
        self.client = Client()
        self.client.login(username='stocktest', password='testpass123')

    def test_add_stock_saves_custom_generic_name(self):
        resp = self.client.post('/pharmacy/add/', {
            'custom_name': 'Clinico Oint 30g',
            'custom_generic_name': 'Clindamycin 1% w/w',
            'quantity': 20,
            'unit_price': '50.00',
            'reorder_level': 5,
        })
        self.assertEqual(resp.status_code, 302)
        item = PharmacyItem.objects.get(clinic=self.clinic, custom_name='Clinico Oint 30g')
        self.assertEqual(item.custom_generic_name, 'Clindamycin 1% w/w')

    def test_add_stock_catalog_medicine_ignores_custom_generic(self):
        med = make_catalog_medicine(name='Metformin 500mg', generic='Metformin')
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': med.pk,
            'custom_generic_name': 'Should be ignored',
            'quantity': 10,
            'unit_price': '5.00',
            'reorder_level': 10,
        })
        self.assertEqual(resp.status_code, 302)
        item = PharmacyItem.objects.get(clinic=self.clinic, medicine=med)
        self.assertEqual(item.custom_generic_name, '')

    def test_add_stock_updates_custom_generic_on_existing_item(self):
        # Create item without generic first
        item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Old Custom Med',
            custom_generic_name='',
            reorder_level=5,
        )
        PharmacyBatch.objects.create(item=item, quantity=10)
        # Add another batch, now with generic
        self.client.post('/pharmacy/add/', {
            'custom_name': 'Old Custom Med',
            'custom_generic_name': 'Betamethasone 0.1%',
            'quantity': 5,
            'unit_price': '10.00',
            'reorder_level': 5,
        })
        item.refresh_from_db()
        self.assertEqual(item.custom_generic_name, 'Betamethasone 0.1%')


class PharmacySearchByGenericTest(TestCase):
    """Inventory search (used by add_stock page) should match custom_generic_name."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user(username='srchtest', clinic_name='Search Clinic')
        self.item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Clinico Ointment',
            custom_generic_name='Clindamycin 1% w/w',
            reorder_level=5,
        )
        PharmacyBatch.objects.create(item=self.item, quantity=50, unit_price=30)
        self.client = Client()
        self.client.login(username='srchtest', password='testpass123')

    def test_inventory_search_finds_item_by_custom_generic(self):
        resp = self.client.get('/pharmacy/api/search/?q=Clindamycin')
        data = resp.json()
        names = [i['name'] for i in data['items']]
        self.assertIn('Clinico Ointment', names)

    def test_inventory_search_finds_item_by_custom_name(self):
        resp = self.client.get('/pharmacy/api/search/?q=Clinico')
        data = resp.json()
        names = [i['name'] for i in data['items']]
        self.assertIn('Clinico Ointment', names)

    def test_inventory_search_no_match_returns_empty(self):
        resp = self.client.get('/pharmacy/api/search/?q=Aspirin')
        data = resp.json()
        self.assertEqual(data['items'], [])


class ExpiryTierModelTest(TestCase):
    """Tests for 3-month (red) and 6-month (orange) expiry tiers."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user(username='exptest', clinic_name='Exp Clinic')
        self.med = make_catalog_medicine(name='TestDrug', generic='TestGeneric')
        self.item = PharmacyItem.objects.create(clinic=self.clinic, medicine=self.med, reorder_level=5)

    def _batch_with_days(self, days):
        from django.utils import timezone
        import datetime
        expiry = timezone.now().date() + datetime.timedelta(days=days)
        return PharmacyBatch(item=self.item, quantity=10, expiry_date=expiry)

    def test_is_near_expiry_true_at_90_days(self):
        batch = self._batch_with_days(90)
        self.assertTrue(batch.is_near_expiry)

    def test_is_near_expiry_true_at_60_days(self):
        batch = self._batch_with_days(60)
        self.assertTrue(batch.is_near_expiry)

    def test_is_near_expiry_false_at_91_days(self):
        batch = self._batch_with_days(91)
        self.assertFalse(batch.is_near_expiry)

    def test_is_approaching_expiry_true_at_120_days(self):
        batch = self._batch_with_days(120)
        self.assertTrue(batch.is_approaching_expiry)

    def test_is_approaching_expiry_true_at_180_days(self):
        batch = self._batch_with_days(180)
        self.assertTrue(batch.is_approaching_expiry)

    def test_is_approaching_expiry_false_at_181_days(self):
        batch = self._batch_with_days(181)
        self.assertFalse(batch.is_approaching_expiry)

    def test_is_approaching_expiry_false_at_90_days(self):
        # 90 days is near_expiry (red), NOT approaching (orange)
        batch = self._batch_with_days(90)
        self.assertFalse(batch.is_approaching_expiry)

    def test_is_approaching_expiry_false_when_no_expiry(self):
        batch = PharmacyBatch(item=self.item, quantity=10, expiry_date=None)
        self.assertFalse(batch.is_approaching_expiry)

    def test_is_approaching_expiry_false_when_expired(self):
        from django.utils import timezone
        import datetime
        past = timezone.now().date() - datetime.timedelta(days=10)
        batch = PharmacyBatch(item=self.item, quantity=10, expiry_date=past)
        self.assertFalse(batch.is_approaching_expiry)


class ExpiryDashboardContextTest(TestCase):
    """Tests that pharmacy dashboard passes correct expiry counts to template."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user(username='dashexp', clinic_name='DashExp Clinic')
        self.client = Client()
        self.client.login(username='dashexp', password='testpass123')
        self.med = make_catalog_medicine(name='DashDrug', generic='DashGeneric')
        self.item = PharmacyItem.objects.create(clinic=self.clinic, medicine=self.med, reorder_level=5)

    def _create_batch(self, days, qty=10):
        from django.utils import timezone
        import datetime
        expiry = timezone.now().date() + datetime.timedelta(days=days)
        return PharmacyBatch.objects.create(item=self.item, quantity=qty, expiry_date=expiry)

    def test_expiring_3m_count_in_context(self):
        self._create_batch(60)  # within 90 days
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.context['expiring_3m_count'], 1)

    def test_expiring_6m_count_in_context(self):
        self._create_batch(150)  # 90–180 days
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.context['expiring_6m_count'], 1)

    def test_expired_batch_not_counted_in_3m(self):
        from django.utils import timezone
        import datetime
        past = timezone.now().date() - datetime.timedelta(days=5)
        PharmacyBatch.objects.create(item=self.item, quantity=10, expiry_date=past)
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.context['expiring_3m_count'], 0)

    def test_empty_batch_not_counted(self):
        self._create_batch(60, qty=0)  # quantity=0, should not count
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.context['expiring_3m_count'], 0)

    def test_far_future_batch_not_counted(self):
        self._create_batch(365)  # > 6 months
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.context['expiring_3m_count'], 0)
        self.assertEqual(resp.context['expiring_6m_count'], 0)


# ===========================================================================
# Phase 5 — Dispensing, Billing, Bill Scanning tests
# ===========================================================================

import json
import decimal
from pharmacy.models import DispensedItem, PharmacyBill
from reception.models import Patient, Visit
from prescription.models import Prescription, PrescriptionMedicine


def make_patient_and_visit(clinic, username_suffix='disp'):
    patient = Patient.objects.create(
        clinic=clinic, full_name='Test Patient', phone=f'9{username_suffix[:9]}',
        gender='M', age=40,
    )
    visit = Visit.objects.create(
        clinic=clinic, patient=patient, token_number=1,
        visit_date=timezone.now().date(), status='done',
    )
    return patient, visit


def make_prescription(visit, staff, medicines=None):
    rx = Prescription.objects.create(
        visit=visit, doctor=staff, raw_clinical_note='Test note',
        diagnosis='Test diagnosis',
    )
    if medicines:
        for i, m in enumerate(medicines):
            PrescriptionMedicine.objects.create(
                prescription=rx,
                drug_name=m['drug_name'],
                dosage=m['dosage'],
                frequency=m.get('frequency', 'twice daily'),
                duration=m['duration'],
                order=i,
            )
    return rx


def make_item_with_batch(clinic, name='Metformin 500mg', generic='Metformin', qty=100, price='5.00'):
    item = PharmacyItem.objects.create(
        clinic=clinic, custom_name=name, custom_generic_name=generic, reorder_level=10,
    )
    batch = PharmacyBatch.objects.create(
        item=item, batch_number='B001',
        expiry_date=today() + datetime.timedelta(days=180),
        quantity=qty, unit_price=price,
    )
    return item, batch


# ---------------------------------------------------------------------------
# _calc_qty unit tests
# ---------------------------------------------------------------------------

class CalcQtyTest(TestCase):

    def _calc(self, dosage, duration):
        from pharmacy.views import _calc_qty
        return _calc_qty(dosage, duration)

    def test_1_0_1_30_days(self):
        self.assertEqual(self._calc('1-0-1', '30 days'), 60)

    def test_1_1_1_7_days(self):
        self.assertEqual(self._calc('1-1-1', '7 days'), 21)

    def test_0_0_1_14_days(self):
        self.assertEqual(self._calc('0-0-1', '14 days'), 14)

    def test_1_0_0_2_weeks(self):
        self.assertEqual(self._calc('1-0-0', '2 weeks'), 14)

    def test_1_0_1_1_month(self):
        self.assertEqual(self._calc('1-0-1', '1 month'), 60)

    def test_din_duration(self):
        self.assertEqual(self._calc('1-0-1', '10 din'), 20)

    def test_sos_returns_1(self):
        # SOS / as needed cannot be parsed → fallback 1
        self.assertEqual(self._calc('SOS', 'as needed'), 1)

    def test_empty_dosage_returns_1(self):
        self.assertEqual(self._calc('', '7 days'), 1)

    def test_empty_duration_returns_1(self):
        self.assertEqual(self._calc('1-0-1', ''), 1)


# ---------------------------------------------------------------------------
# DispensedItem + PharmacyBill model tests
# ---------------------------------------------------------------------------

class DispensedItemModelTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('dispmodel')
        self.patient, self.visit = make_patient_and_visit(self.clinic)
        self.item, self.batch = make_item_with_batch(self.clinic)

    def test_dispensed_item_creation(self):
        di = DispensedItem.objects.create(
            visit=self.visit,
            pharmacy_item=self.item,
            batch=self.batch,
            quantity_dispensed=10,
            unit_price=decimal.Decimal('5.00'),
            dispensed_by=self.staff,
        )
        self.assertEqual(di.quantity_dispensed, 10)
        self.assertFalse(di.is_substitute)

    def test_bill_number_format(self):
        today_str = timezone.localdate().strftime('%Y%m%d')
        num = PharmacyBill.generate_bill_number(self.clinic.pk)
        self.assertTrue(num.startswith(f'BILL-{today_str}-'))

    def test_bill_number_sequential(self):
        n1 = PharmacyBill.generate_bill_number(self.clinic.pk)
        # Create a bill so count increases
        bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number=n1, subtotal=100, final_amount=100,
        )
        n2 = PharmacyBill.generate_bill_number(self.clinic.pk)
        self.assertNotEqual(n1, n2)

    def test_bill_final_amount_with_discount(self):
        """final_amount should reflect discount_percent applied to subtotal."""
        bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-TEST-0001',
            subtotal=decimal.Decimal('100.00'),
            discount_percent=10,
            final_amount=decimal.Decimal('90.00'),
        )
        self.assertEqual(bill.final_amount, decimal.Decimal('90.00'))


# ---------------------------------------------------------------------------
# Dispense view tests
# ---------------------------------------------------------------------------

class DispenseViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('dispensev')
        self.patient, self.visit = make_patient_and_visit(self.clinic, 'dv')
        self.item, self.batch = make_item_with_batch(self.clinic, qty=100)
        self.client = Client()
        self.client.login(username='dispensev', password='testpass123')
        self.url = f'/pharmacy/dispense/{self.visit.id}/'
        self.confirm_url = f'/pharmacy/dispense/{self.visit.id}/confirm/'

    # --- GET tests ---

    def test_dispense_page_loads(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_dispense_page_requires_login(self):
        anon = Client()
        resp = anon.get(self.url)
        self.assertIn(resp.status_code, [302, 403])

    def test_dispense_wrong_clinic_returns_404(self):
        other_clinic, other_user, _ = make_clinic_and_user('other_disp', 'Other Clinic')
        other_patient = Patient.objects.create(
            clinic=other_clinic, full_name='Other', phone='9888888888', gender='M', age=30,
        )
        other_visit = Visit.objects.create(
            clinic=other_clinic, patient=other_patient, token_number=1,
            visit_date=timezone.now().date(),
        )
        resp = self.client.get(f'/pharmacy/dispense/{other_visit.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_dispense_with_prescription_shows_medicines(self):
        make_prescription(self.visit, self.staff, [
            {'drug_name': 'Metformin 500mg', 'dosage': '1-0-1', 'duration': '30 days'},
        ])
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Metformin', str(resp.content))

    def test_dispense_no_prescription_still_loads(self):
        # No prescription created — should show empty state
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    # --- POST confirm tests ---

    def _confirm_payload(self, qty=10, discount=0, payment='cash'):
        return json.dumps({
            'items': [{
                'batch_id': self.batch.pk,
                'pharmacy_item_id': self.item.pk,
                'prescription_med_id': None,
                'qty': qty,
                'is_substitute': False,
                'notes': '',
            }],
            'discount': discount,
            'payment_mode': payment,
        })

    def test_confirm_dispense_creates_bill(self):
        resp = self.client.post(
            self.confirm_url,
            data=self._confirm_payload(qty=10),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(PharmacyBill.objects.filter(visit=self.visit).exists())

    def test_confirm_dispense_decrements_batch_quantity(self):
        original_qty = self.batch.quantity
        self.client.post(
            self.confirm_url,
            data=self._confirm_payload(qty=15),
            content_type='application/json',
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, original_qty - 15)

    def test_confirm_dispense_creates_dispensed_items(self):
        self.client.post(
            self.confirm_url,
            data=self._confirm_payload(qty=5),
            content_type='application/json',
        )
        self.assertEqual(DispensedItem.objects.filter(visit=self.visit).count(), 1)

    def test_confirm_dispense_prevents_overdispense(self):
        resp = self.client.post(
            self.confirm_url,
            data=self._confirm_payload(qty=9999),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_confirm_dispense_prevents_double_billing(self):
        # First dispense
        self.client.post(
            self.confirm_url,
            data=self._confirm_payload(qty=5),
            content_type='application/json',
        )
        # Second attempt
        _, batch2 = make_item_with_batch(self.clinic, name='Atenolol 50mg', qty=50)
        payload = json.dumps({
            'items': [{'batch_id': batch2.pk, 'qty': 5, 'is_substitute': False, 'notes': ''}],
            'discount': 0, 'payment_mode': 'cash',
        })
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('already has a bill', resp.json()['error'])

    def test_confirm_dispense_with_discount(self):
        resp = self.client.post(
            self.confirm_url,
            data=self._confirm_payload(qty=10, discount=10),
            content_type='application/json',
        )
        bill = PharmacyBill.objects.get(visit=self.visit)
        # subtotal = 10 * 5.00 = 50; discount 10% = 45
        self.assertEqual(bill.discount_percent, 10)
        self.assertEqual(bill.final_amount, decimal.Decimal('45.00'))

    def test_confirm_dispense_empty_items_returns_400(self):
        payload = json.dumps({'items': [], 'discount': 0, 'payment_mode': 'cash'})
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_confirm_dispense_wrong_clinic_returns_404(self):
        other_clinic, other_user, _ = make_clinic_and_user('other_conf', 'Other Conf Clinic')
        other_patient = Patient.objects.create(
            clinic=other_clinic, full_name='Other', phone='9777777777', gender='F', age=25,
        )
        other_visit = Visit.objects.create(
            clinic=other_clinic, patient=other_patient, token_number=1,
            visit_date=timezone.now().date(),
        )
        resp = self.client.post(
            f'/pharmacy/dispense/{other_visit.id}/confirm/',
            data=self._confirm_payload(),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Bill view tests
# ---------------------------------------------------------------------------

class BillViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('billview')
        self.patient, self.visit = make_patient_and_visit(self.clinic, 'bv')
        self.item, self.batch = make_item_with_batch(self.clinic, qty=50)
        self.bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-TEST-0001',
            subtotal=decimal.Decimal('50.00'),
            final_amount=decimal.Decimal('50.00'),
        )
        self.client = Client()
        self.client.login(username='billview', password='testpass123')

    def test_bill_view_loads(self):
        resp = self.client.get(f'/pharmacy/bill/{self.bill.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_bill_view_wrong_clinic_404(self):
        other_clinic, other_user, _ = make_clinic_and_user('other_bill', 'Other Bill Clinic')
        other_patient = Patient.objects.create(
            clinic=other_clinic, full_name='Other', phone='9666666666', gender='M', age=50,
        )
        other_visit = Visit.objects.create(
            clinic=other_clinic, patient=other_patient, token_number=1,
            visit_date=timezone.now().date(),
        )
        other_bill = PharmacyBill.objects.create(
            visit=other_visit, clinic=other_clinic,
            bill_number='BILL-OTHER-0001',
            subtotal=100, final_amount=100,
        )
        resp = self.client.get(f'/pharmacy/bill/{other_bill.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_bill_view_requires_login(self):
        anon = Client()
        resp = anon.get(f'/pharmacy/bill/{self.bill.pk}/')
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Alternatives API tests
# ---------------------------------------------------------------------------

class AlternativesApiTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('alttest')
        self.client = Client()
        self.client.login(username='alttest', password='testpass123')

    def test_alternatives_returns_matching_generic(self):
        """Items with the same generic name should appear as alternatives."""
        item1, _ = make_item_with_batch(self.clinic, name='Metformin 500mg (Sun)', generic='Metformin', qty=0)
        item2, _ = make_item_with_batch(self.clinic, name='Metformin 500mg (Cipla)', generic='Metformin', qty=50)
        resp = self.client.get(f'/pharmacy/api/alternatives/{item1.pk}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        names = [i['name'] for i in data['alternatives']]
        self.assertIn(item2.display_name, names)

    def test_alternatives_excludes_out_of_stock(self):
        """Alternatives with no stock should not appear."""
        item1, _ = make_item_with_batch(self.clinic, name='Atenolol 50mg (Sun)', generic='Atenolol', qty=0)
        item2, _ = make_item_with_batch(self.clinic, name='Atenolol 50mg (Cipla)', generic='Atenolol', qty=0)
        resp = self.client.get(f'/pharmacy/api/alternatives/{item1.pk}/')
        data = resp.json()
        self.assertEqual(len(data['alternatives']), 0)

    def test_alternatives_excludes_self(self):
        """The requested item itself should not appear in alternatives."""
        item1, _ = make_item_with_batch(self.clinic, name='Ramipril 5mg (Sun)', generic='Ramipril', qty=50)
        item2, _ = make_item_with_batch(self.clinic, name='Ramipril 5mg (Cipla)', generic='Ramipril', qty=50)
        resp = self.client.get(f'/pharmacy/api/alternatives/{item1.pk}/')
        data = resp.json()
        ids = [i['id'] for i in data['alternatives']]
        self.assertNotIn(item1.pk, ids)

    def test_alternatives_wrong_clinic_returns_404(self):
        other_clinic, _, _ = make_clinic_and_user('otheralt', 'Alt Clinic')
        item, _ = make_item_with_batch(other_clinic, name='Atenolol 50mg', qty=50)
        resp = self.client.get(f'/pharmacy/api/alternatives/{item.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_alternatives_requires_login(self):
        item, _ = make_item_with_batch(self.clinic, qty=50)
        anon = Client()
        resp = anon.get(f'/pharmacy/api/alternatives/{item.pk}/')
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Regression — existing pharmacy features still work
# ---------------------------------------------------------------------------

class RegressionPharmacyTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('regpharm')
        self.client = Client()
        self.client.login(username='regpharm', password='testpass123')
        self.item, self.batch = make_item_with_batch(self.clinic, qty=100)

    def test_pharmacy_dashboard_loads(self):
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.status_code, 200)

    def test_add_stock_page_loads(self):
        resp = self.client.get('/pharmacy/add/')
        self.assertEqual(resp.status_code, 200)

    def test_catalog_search_api_works(self):
        resp = self.client.get('/pharmacy/api/catalog/?q=Para')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('items', resp.json())

    def test_inventory_search_api_works(self):
        resp = self.client.get('/pharmacy/api/search/?q=Metformin')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('items', data)
        self.assertEqual(len(data['items']), 1)

    def test_add_stock_creates_item(self):
        resp = self.client.post('/pharmacy/add/', {
            'custom_name': 'Regression Medicine',
            'batch_number': 'B999',
            'quantity': 50,
            'unit_price': '3.00',
            'reorder_level': 5,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PharmacyItem.objects.filter(clinic=self.clinic, custom_name='Regression Medicine').exists())

    def test_scan_page_loads(self):
        resp = self.client.get('/pharmacy/scan/')
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Edit PharmacyItem (generic composition + name)
# ---------------------------------------------------------------------------

class EditItemViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, _ = make_clinic_and_user('edititem_doc', 'Edit Item Clinic')
        self.client = Client()
        self.client.login(username='edititem_doc', password='testpass123')
        self.item = PharmacyItem.objects.create(
            clinic=self.clinic,
            custom_name='Cliza Ointment',
            custom_generic_name='',
            reorder_level=5,
        )
        PharmacyBatch.objects.create(item=self.item, quantity=20, unit_price=50)

    def test_edit_page_loads(self):
        resp = self.client.get(f'/pharmacy/item/{self.item.pk}/edit/')
        self.assertEqual(resp.status_code, 200)

    def test_edit_generic_name_saves(self):
        self.client.post(f'/pharmacy/item/{self.item.pk}/edit/', {
            'custom_name': 'Cliza Ointment',
            'custom_generic_name': 'Clotrimazole 1%',
            'reorder_level': 5,
        })
        self.item.refresh_from_db()
        self.assertEqual(self.item.custom_generic_name, 'Clotrimazole 1%')

    def test_edit_name_saves(self):
        self.client.post(f'/pharmacy/item/{self.item.pk}/edit/', {
            'custom_name': 'Cliza Plus Ointment',
            'custom_generic_name': 'Clotrimazole 1%',
            'reorder_level': 5,
        })
        self.item.refresh_from_db()
        self.assertEqual(self.item.custom_name, 'Cliza Plus Ointment')

    def test_edit_reorder_level_saves(self):
        self.client.post(f'/pharmacy/item/{self.item.pk}/edit/', {
            'custom_name': 'Cliza Ointment',
            'custom_generic_name': '',
            'reorder_level': 20,
        })
        self.item.refresh_from_db()
        self.assertEqual(self.item.reorder_level, 20)

    def test_edit_redirects_to_dashboard(self):
        resp = self.client.post(f'/pharmacy/item/{self.item.pk}/edit/', {
            'custom_name': 'Cliza Ointment',
            'custom_generic_name': 'Clotrimazole 1%',
            'reorder_level': 5,
        })
        self.assertRedirects(resp, '/pharmacy/')

    def test_cannot_edit_other_clinics_item(self):
        other_clinic = Clinic.objects.create(name='Other Clinic', address='x', city='Delhi', phone='9000000099')
        other_item = PharmacyItem.objects.create(clinic=other_clinic, custom_name='Other Drug', reorder_level=0)
        PharmacyBatch.objects.create(item=other_item, quantity=10, unit_price=10)
        resp = self.client.post(f'/pharmacy/item/{other_item.pk}/edit/', {
            'custom_name': 'Hacked',
            'custom_generic_name': '',
            'reorder_level': 0,
        })
        self.assertEqual(resp.status_code, 404)

    def test_catalog_medicine_generic_not_overwritten(self):
        catalog = make_catalog_medicine('Metformin', 'Metformin HCl')
        catalog_item = PharmacyItem.objects.create(
            clinic=self.clinic, medicine=catalog, reorder_level=5,
        )
        PharmacyBatch.objects.create(item=catalog_item, quantity=10, unit_price=5)
        self.client.post(f'/pharmacy/item/{catalog_item.pk}/edit/', {
            'custom_name': 'Hacked Name',
            'custom_generic_name': 'Hacked Generic',
            'reorder_level': 10,
        })
        catalog_item.refresh_from_db()
        # Catalog items: custom_generic_name should not be changed (medicine FK present)
        self.assertEqual(catalog_item.custom_name, '')
        self.assertEqual(catalog_item.custom_generic_name, '')

    def test_edit_requires_login(self):
        anon = Client()
        resp = anon.get(f'/pharmacy/item/{self.item.pk}/edit/')
        self.assertIn(resp.status_code, [302, 403])


# ===========================================================================
# New API / Walk-in / Edit Bill Tests
# ===========================================================================

import decimal as _decimal
from django.utils import timezone as _tz


def _make_clinic(name='Test Clinic'):
    return Clinic.objects.create(name=name, address='1 Rd', city='Mumbai', phone='9000000099')


def _make_user(username, password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def _make_staff(user, clinic, role='pharmacist'):
    sm = StaffMember.objects.create(user=user, clinic=clinic, role=role, display_name='Test Staff')
    set_permissions_from_role(sm)
    sm.save()
    return sm


def _make_item(clinic, name='Paracetamol 500mg'):
    cat = MedicineCatalog.objects.create(name=name, generic_name='Paracetamol')
    return PharmacyItem.objects.create(clinic=clinic, medicine=cat)


def _make_batch(item, qty=50, price='10.00', batch_no='B001'):
    return PharmacyBatch.objects.create(
        item=item, batch_number=batch_no, quantity=qty,
        unit_price=_decimal.Decimal(price),
        expiry_date=datetime.date.today() + datetime.timedelta(days=365),
    )


def _make_patient(clinic, phone='9876543210'):
    from reception.models import Patient
    return Patient.objects.create(
        full_name='Test Patient', phone=phone, clinic=clinic,
        age=30, gender='M',
    )


def _make_visit(patient, clinic):
    from reception.models import Visit
    return Visit.objects.create(
        patient=patient, clinic=clinic,
        visit_date=_tz.now().date(), token_number=1, status='done',
    )


class ItemDetailApiTest(TestCase):
    def setUp(self):
        self.clinic = _make_clinic()
        self.user = _make_user('pharm_api')
        _make_staff(self.user, self.clinic)
        self.item = _make_item(self.clinic)
        self.batch = _make_batch(self.item)
        self.client = Client()
        self.client.login(username='pharm_api', password='testpass123')

    def test_returns_item_details(self):
        resp = self.client.get(f'/pharmacy/api/item-detail/?id={self.item.pk}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['id'], self.item.pk)
        self.assertIn('Paracetamol', data['name'])
        self.assertEqual(data['batch_id'], self.batch.pk)
        self.assertTrue(data['in_stock'])

    def test_404_for_wrong_clinic(self):
        other_clinic = _make_clinic('Other')
        other_item = _make_item(other_clinic, 'Ibuprofen')
        resp = self.client.get(f'/pharmacy/api/item-detail/?id={other_item.pk}')
        self.assertEqual(resp.status_code, 404)

    def test_requires_login(self):
        c = Client()
        resp = c.get(f'/pharmacy/api/item-detail/?id={self.item.pk}')
        self.assertEqual(resp.status_code, 302)


class WalkInViewTest(TestCase):
    def setUp(self):
        self.clinic = _make_clinic()
        self.user = _make_user('walkin_user')
        _make_staff(self.user, self.clinic)
        self.client = Client()
        self.client.login(username='walkin_user', password='testpass123')

    def test_get_walk_in_page(self):
        resp = self.client.get('/pharmacy/walk-in/')
        self.assertEqual(resp.status_code, 200)

    def test_select_existing_patient_creates_visit(self):
        from reception.models import Visit
        patient = _make_patient(self.clinic, phone='9111222333')
        resp = self.client.post('/pharmacy/walk-in/', {
            'action': 'select',
            'patient_id': patient.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Visit.objects.filter(patient=patient, clinic=self.clinic).exists())

    def test_select_existing_patient_reuses_todays_visit(self):
        from reception.models import Visit
        patient = _make_patient(self.clinic, phone='9111222334')
        visit = _make_visit(patient, self.clinic)
        resp = self.client.post('/pharmacy/walk-in/', {
            'action': 'select',
            'patient_id': patient.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Visit.objects.filter(patient=patient, clinic=self.clinic).count(), 1)

    def test_register_new_patient_creates_patient_and_visit(self):
        from reception.models import Patient, Visit
        resp = self.client.post('/pharmacy/walk-in/', {
            'action': 'register',
            'full_name': 'New Patient',
            'phone': '9000111222',
            'age': '25',
            'gender': 'F',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Patient.objects.filter(phone='9000111222', clinic=self.clinic).exists())
        patient = Patient.objects.get(phone='9000111222', clinic=self.clinic)
        self.assertTrue(Visit.objects.filter(patient=patient, clinic=self.clinic).exists())

    def test_register_missing_name_shows_error(self):
        resp = self.client.post('/pharmacy/walk-in/', {
            'action': 'register',
            'full_name': '',
            'phone': '9000111223',
        })
        self.assertEqual(resp.status_code, 200)

    def test_requires_login(self):
        c = Client()
        resp = c.get('/pharmacy/walk-in/')
        self.assertEqual(resp.status_code, 302)


class EditBillTest(TestCase):
    def setUp(self):
        from pharmacy.models import DispensedItem, PharmacyBill
        self.clinic = _make_clinic()
        self.user = _make_user('edit_bill_user')
        self.sm = _make_staff(self.user, self.clinic)
        self.patient = _make_patient(self.clinic, phone='9999888777')
        self.visit = _make_visit(self.patient, self.clinic)
        self.item = _make_item(self.clinic)
        self.batch = _make_batch(self.item, qty=50)
        # Create a dispensed item
        DispensedItem.objects.create(
            visit=self.visit, pharmacy_item=self.item,
            batch=self.batch, quantity_dispensed=5,
            unit_price=_decimal.Decimal('10.00'),
            dispensed_by=self.sm,
        )
        self.bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-TEST-0001',
            subtotal=_decimal.Decimal('50.00'),
            discount_percent=0,
            final_amount=_decimal.Decimal('50.00'),
            payment_mode='cash',
            created_by=self.sm,
        )
        # Deplete stock (as dispense would)
        self.batch.quantity = 45  # was 50, dispensed 5
        self.batch.save()
        self.client = Client()
        self.client.login(username='edit_bill_user', password='testpass123')

    def test_edit_bill_reverses_stock(self):
        from pharmacy.models import PharmacyBill
        resp = self.client.post(f'/pharmacy/bill/{self.bill.pk}/edit/')
        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 50)  # stock restored

    def test_edit_bill_deletes_bill(self):
        from pharmacy.models import PharmacyBill
        pk = self.bill.pk
        self.client.post(f'/pharmacy/bill/{pk}/edit/')
        self.assertFalse(PharmacyBill.objects.filter(pk=pk).exists())

    def test_edit_bill_deletes_dispensed_items(self):
        from pharmacy.models import DispensedItem
        self.client.post(f'/pharmacy/bill/{self.bill.pk}/edit/')
        self.assertFalse(DispensedItem.objects.filter(visit=self.visit).exists())

    def test_edit_bill_redirects_to_dispense(self):
        resp = self.client.post(f'/pharmacy/bill/{self.bill.pk}/edit/')
        self.assertRedirects(resp, f'/pharmacy/dispense/{self.visit.id}/', fetch_redirect_response=False)

    def test_cannot_edit_other_clinics_bill(self):
        from pharmacy.models import PharmacyBill
        other_clinic = _make_clinic('Other')
        other_user = _make_user('other_pharm')
        _make_staff(other_user, other_clinic)
        c = Client()
        c.login(username='other_pharm', password='testpass123')
        resp = c.post(f'/pharmacy/bill/{self.bill.pk}/edit/')
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Tests for _calc_qty: quantity calculation for different preparations
# ---------------------------------------------------------------------------

from pharmacy.views import _calc_qty


class CalcQtyTabletTest(TestCase):
    """Tablets/capsules: qty = per_day × days"""

    def test_tab_twice_daily_5_days(self):
        self.assertEqual(_calc_qty('1-0-1', '5 days', 'Tab Metformin 500mg'), 10)

    def test_tab_thrice_daily_7_days(self):
        self.assertEqual(_calc_qty('1-1-1', '7 days', 'Cap Amoxicillin 500mg'), 21)

    def test_tab_once_daily_1_month(self):
        self.assertEqual(_calc_qty('1-0-0', '1 month', 'Tab Atorvastatin 10mg'), 30)

    def test_tab_once_daily_2_weeks(self):
        self.assertEqual(_calc_qty('1-0-0', '2 weeks', 'Tab Pantoprazole'), 14)

    def test_tab_sos(self):
        # SOS dosage: "SOS" → can't parse to int, falls back to 1
        self.assertEqual(_calc_qty('SOS', '5 days', 'Tab Crocin'), 1)

    def test_no_duration(self):
        self.assertEqual(_calc_qty('1-0-1', '', 'Tab Metformin'), 1)

    def test_no_dosage(self):
        self.assertEqual(_calc_qty('', '5 days', 'Tab Metformin'), 1)


class CalcQtyUnitDispenseTest(TestCase):
    """Syrups, ointments, creams, lotions etc. must always return 1."""

    # --- Syrup ---
    def test_syrup_twice_daily_5_days_returns_1(self):
        self.assertEqual(_calc_qty('1-0-1', '5 days', 'Cough Syrup'), 1)

    def test_syrup_case_insensitive(self):
        self.assertEqual(_calc_qty('1-1-1', '7 days', 'BENADRYL SYRUP'), 1)

    def test_syrup_thrice_daily_10_days_returns_1(self):
        self.assertEqual(_calc_qty('1-1-1', '10 days', 'Syrup Amoxicillin 125mg'), 1)

    # --- Ointment ---
    def test_ointment_twice_daily_5_days_returns_1(self):
        self.assertEqual(_calc_qty('1-0-1', '5 days', 'Mupirocin Ointment'), 1)

    def test_ointment_word_anywhere(self):
        self.assertEqual(_calc_qty('1-0-1', '7 days', 'Apply Ointment BD'), 1)

    # --- Cream ---
    def test_cream_twice_daily_returns_1(self):
        self.assertEqual(_calc_qty('1-0-1', '5 days', 'Betnovate Cream'), 1)

    def test_cream_mixed_case(self):
        self.assertEqual(_calc_qty('1-0-0', '14 days', 'Clotrimazole CREAM'), 1)

    # --- Lotion ---
    def test_lotion_returns_1(self):
        self.assertEqual(_calc_qty('1-0-1', '5 days', 'Calamine Lotion'), 1)

    # --- Gel ---
    def test_gel_returns_1(self):
        self.assertEqual(_calc_qty('1-0-1', '7 days', 'Diclofenac Gel'), 1)

    # --- Drops ---
    def test_drops_returns_1(self):
        self.assertEqual(_calc_qty('1-0-1', '5 days', 'Eye Drops Tobramycin'), 1)

    def test_drop_singular_returns_1(self):
        self.assertEqual(_calc_qty('2-2-2', '10 days', 'Ear Drop'), 1)

    # --- Suspension ---
    def test_suspension_returns_1(self):
        self.assertEqual(_calc_qty('1-1-1', '5 days', 'Azithromycin Suspension'), 1)

    # --- Solution ---
    def test_solution_returns_1(self):
        self.assertEqual(_calc_qty('1-0-0', '7 days', 'Povidone Solution'), 1)

    # --- Patch ---
    def test_patch_returns_1(self):
        self.assertEqual(_calc_qty('1-0-0', '7 days', 'Nicotine Patch'), 1)

    # --- Spray ---
    def test_spray_returns_1(self):
        self.assertEqual(_calc_qty('1-0-1', '14 days', 'Nasal Spray'), 1)

    # --- Powder / Sachet ---
    def test_powder_returns_1(self):
        self.assertEqual(_calc_qty('1-0-0', '5 days', 'Dusting Powder'), 1)

    def test_sachet_returns_1(self):
        self.assertEqual(_calc_qty('1-0-0', '5 days', 'ORS Sachet'), 1)

    # --- Edge: drug name contains "cream" as substring of tablet name ---
    def test_cream_in_name_correctly_detected(self):
        # "Icecream Tab" should NOT be 1 — wait, it contains "cream"
        # Actually this is an edge case we accept: if "cream" appears in any form we return 1
        # The regex uses \b word boundary so "Icecream" won't match "cream" as a word
        self.assertNotEqual(_calc_qty('1-0-1', '5 days', 'Icecream flavored Tab'), 1)
        # But "Ice Cream" would match
        self.assertEqual(_calc_qty('1-0-1', '5 days', 'Ice Cream topical'), 1)

    # --- No drug name: falls through to calculation ---
    def test_no_drug_name_calculates_normally(self):
        self.assertEqual(_calc_qty('1-0-1', '5 days', ''), 10)


# ---------------------------------------------------------------------------
# Tests for dispense_view: accessible without prescription
# ---------------------------------------------------------------------------

import uuid as _uuid
from reception.models import Patient, Visit


def _make_visit_fresh(clinic, status='waiting'):
    patient = Patient.objects.create(
        clinic=clinic, full_name='Test Patient',
        phone='9000099999', age=30, gender='M',
    )
    visit = Visit.objects.create(
        clinic=clinic, patient=patient,
        visit_date=timezone.now().date(),
        status=status, token_number=1,
    )
    return patient, visit


class DispenseViewNoPrescriptionTest(TestCase):
    """Dispense screen must be accessible even with no prescription."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('disp_nopx')
        self.client = Client()
        self.client.login(username='disp_nopx', password='testpass123')
        self.patient, self.visit = _make_visit_fresh(self.clinic, status='waiting')

    def test_dispense_accessible_with_waiting_visit(self):
        resp = self.client.get(f'/pharmacy/dispense/{self.visit.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_dispense_accessible_with_done_visit(self):
        self.visit.status = 'done'
        self.visit.save()
        resp = self.client.get(f'/pharmacy/dispense/{self.visit.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_dispense_page_contains_med_list(self):
        """#med-list must always exist in the HTML even with no prescription."""
        resp = self.client.get(f'/pharmacy/dispense/{self.visit.id}/')
        self.assertContains(resp, 'id="med-list"')

    def test_dispense_page_shows_manual_add_section(self):
        resp = self.client.get(f'/pharmacy/dispense/{self.visit.id}/')
        self.assertContains(resp, 'manual-search')

    def test_no_prescription_shows_helpful_message(self):
        resp = self.client.get(f'/pharmacy/dispense/{self.visit.id}/')
        self.assertContains(resp, 'No prescription')


# ---------------------------------------------------------------------------
# Tests for pharmacy dashboard: shows all unbilled visits (not just 'done')
# ---------------------------------------------------------------------------

class PharmacyDashboardPendingDispenseTest(TestCase):
    """Dashboard must show waiting/in_consultation visits, not just done."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('dash_test')
        self.client = Client()
        self.client.login(username='dash_test', password='testpass123')

    def test_waiting_visit_shown_in_pending(self):
        _, visit = _make_visit_fresh(self.clinic, status='waiting')
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'Test Patient')

    def test_in_consultation_visit_shown(self):
        _, visit = _make_visit_fresh(self.clinic, status='in_consultation')
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'Test Patient')

    def test_done_visit_shown(self):
        _, visit = _make_visit_fresh(self.clinic, status='done')
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'Test Patient')

    def test_no_show_visit_not_shown(self):
        _, visit = _make_visit_fresh(self.clinic, status='no_show')
        resp = self.client.get('/pharmacy/')
        self.assertNotContains(resp, 'Test Patient')

    def test_cancelled_visit_not_shown(self):
        _, visit = _make_visit_fresh(self.clinic, status='cancelled')
        resp = self.client.get('/pharmacy/')
        self.assertNotContains(resp, 'Test Patient')

    def test_billed_visit_not_shown(self):
        """A visit that already has a bill should NOT appear in pending."""
        from pharmacy.models import PharmacyBill
        _, visit = _make_visit_fresh(self.clinic, status='done')
        import decimal
        PharmacyBill.objects.create(
            visit=visit, clinic=self.clinic,
            bill_number='B001', subtotal=decimal.Decimal('100'),
            final_amount=decimal.Decimal('100'), payment_mode='cash',
        )
        resp = self.client.get('/pharmacy/')
        self.assertNotContains(resp, 'Test Patient')


# ===========================================================================
# Phase 6 — Bill decimal fix, generic removal, license numbers, medicine return
# ===========================================================================

import decimal as _decimal_module


class BillDecimalAmountTest(TestCase):
    """Bill line amounts must use full decimal precision (not integer-truncated)."""

    def setUp(self):
        self.clinic = _make_clinic('Decimal Clinic')
        self.user = _make_user('decimal_user')
        self.sm = _make_staff(self.user, self.clinic)
        self.patient = _make_patient(self.clinic, phone='9100000001')
        self.visit = _make_visit(self.patient, self.clinic)
        # Price with decimal: Rs 10.75 per unit
        self.item = _make_item(self.clinic, name='Decimal Med')
        self.batch = PharmacyBatch.objects.create(
            item=self.item, batch_number='BD01',
            expiry_date=datetime.date.today() + datetime.timedelta(days=180),
            quantity=100,
            unit_price=_decimal_module.Decimal('10.75'),
        )
        self.client = Client()
        self.client.login(username='decimal_user', password='testpass123')

    def _create_bill(self, qty, price):
        di = DispensedItem.objects.create(
            visit=self.visit,
            pharmacy_item=self.item,
            batch=self.batch,
            quantity_dispensed=qty,
            unit_price=_decimal_module.Decimal(str(price)),
            dispensed_by=self.sm,
        )
        bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-DEC-001',
            subtotal=_decimal_module.Decimal(str(qty * price)),
            final_amount=_decimal_module.Decimal(str(qty * price)),
            payment_mode='cash',
        )
        return bill, di

    def test_line_amount_annotated_correctly_in_view(self):
        """bill_view must annotate item.line_amount = qty * unit_price (decimal)."""
        bill, _ = self._create_bill(3, 10.75)
        resp = self.client.get(f'/pharmacy/bill/{bill.pk}/')
        self.assertEqual(resp.status_code, 200)
        items = resp.context['dispensed_items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].line_amount, _decimal_module.Decimal('32.25'))

    def test_bill_shows_decimal_amount_in_html(self):
        """Bill HTML must show 32.25 not 32 for 3 x 10.75."""
        bill, _ = self._create_bill(3, 10.75)
        resp = self.client.get(f'/pharmacy/bill/{bill.pk}/')
        self.assertContains(resp, '32.25')

    def test_bill_does_not_show_generic_column(self):
        """Generic composition column must not appear in bill HTML."""
        bill, _ = self._create_bill(1, 10.00)
        resp = self.client.get(f'/pharmacy/bill/{bill.pk}/')
        content = resp.content.decode()
        self.assertNotIn('Generic', content)
        self.assertNotIn('Composition', content)


class LicenseNumberBillTest(TestCase):
    """License numbers should appear on bill when set on the clinic."""

    def setUp(self):
        self.clinic = _make_clinic('License Clinic')
        self.clinic.drug_license_number = 'DL-MH-12345'
        self.clinic.medical_license_number = 'ML-MH-67890'
        self.clinic.save()
        self.user = _make_user('license_user')
        _make_staff(self.user, self.clinic)
        self.patient = _make_patient(self.clinic, phone='9100000002')
        self.visit = _make_visit(self.patient, self.clinic)
        self.item = _make_item(self.clinic, name='Lic Med')
        self.batch = _make_batch(self.item, qty=20, price='5.00', batch_no='BL01')
        self.bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-LIC-001',
            subtotal=_decimal_module.Decimal('5.00'),
            final_amount=_decimal_module.Decimal('5.00'),
            payment_mode='cash',
        )
        self.client = Client()
        self.client.login(username='license_user', password='testpass123')

    def test_drug_license_shown_on_bill(self):
        resp = self.client.get(f'/pharmacy/bill/{self.bill.pk}/')
        self.assertContains(resp, 'DL-MH-12345')

    def test_medical_license_shown_on_bill(self):
        resp = self.client.get(f'/pharmacy/bill/{self.bill.pk}/')
        self.assertContains(resp, 'ML-MH-67890')

    def test_bill_loads_without_license_numbers(self):
        """If clinic has no license numbers, bill must still render correctly."""
        self.clinic.drug_license_number = ''
        self.clinic.medical_license_number = ''
        self.clinic.save()
        resp = self.client.get(f'/pharmacy/bill/{self.bill.pk}/')
        self.assertEqual(resp.status_code, 200)


class MedicineReturnTest(TestCase):
    """Medicine return: inventory restored, quantity_returned tracked."""

    def setUp(self):
        self.clinic = _make_clinic('Return Clinic')
        self.user = _make_user('return_user')
        self.sm = _make_staff(self.user, self.clinic)
        self.patient = _make_patient(self.clinic, phone='9100000003')
        self.visit = _make_visit(self.patient, self.clinic)
        self.item = _make_item(self.clinic, name='Return Med')
        self.batch = _make_batch(self.item, qty=45, price='15.00', batch_no='BR01')
        self.di = DispensedItem.objects.create(
            visit=self.visit,
            pharmacy_item=self.item,
            batch=self.batch,
            quantity_dispensed=5,
            unit_price=_decimal_module.Decimal('15.00'),
            dispensed_by=self.sm,
        )
        self.bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-RET-001',
            subtotal=_decimal_module.Decimal('75.00'),
            final_amount=_decimal_module.Decimal('75.00'),
            payment_mode='cash',
            created_by=self.sm,
        )
        self.client = Client()
        self.client.login(username='return_user', password='testpass123')

    def test_return_view_loads_without_bill(self):
        resp = self.client.get('/pharmacy/return/')
        self.assertEqual(resp.status_code, 200)

    def test_return_view_loads_with_bill_id(self):
        resp = self.client.get(f'/pharmacy/return/{self.bill.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_return_view_shows_dispensed_items(self):
        resp = self.client.get(f'/pharmacy/return/{self.bill.pk}/')
        self.assertContains(resp, 'Return Med')

    def test_return_view_bill_lookup_by_number(self):
        resp = self.client.post('/pharmacy/return/', {'bill_number': 'BILL-RET-001'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(str(self.bill.pk), resp['Location'])

    def test_return_view_invalid_bill_shows_error(self):
        resp = self.client.post('/pharmacy/return/', {'bill_number': 'NONEXISTENT-999'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'not found')

    def test_process_return_restores_inventory(self):
        initial_qty = self.batch.quantity
        payload = json.dumps({'returns': [
            {'dispensed_item_id': self.di.pk, 'return_qty': 2}
        ]})
        resp = self.client.post(
            f'/pharmacy/return/{self.bill.pk}/process/',
            data=payload, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, initial_qty + 2)

    def test_process_return_records_quantity_returned(self):
        payload = json.dumps({'returns': [
            {'dispensed_item_id': self.di.pk, 'return_qty': 3}
        ]})
        self.client.post(
            f'/pharmacy/return/{self.bill.pk}/process/',
            data=payload, content_type='application/json',
        )
        self.di.refresh_from_db()
        self.assertEqual(self.di.quantity_returned, 3)

    def test_process_return_calculates_total_returned_amount(self):
        payload = json.dumps({'returns': [
            {'dispensed_item_id': self.di.pk, 'return_qty': 2}
        ]})
        resp = self.client.post(
            f'/pharmacy/return/{self.bill.pk}/process/',
            data=payload, content_type='application/json',
        )
        data = resp.json()
        # 2 × Rs 15.00 = Rs 30.00
        self.assertEqual(_decimal_module.Decimal(data['total_returned']),
                         _decimal_module.Decimal('30.00'))

    def test_process_return_rejects_excess_quantity(self):
        """Cannot return more than what was dispensed."""
        payload = json.dumps({'returns': [
            {'dispensed_item_id': self.di.pk, 'return_qty': 10}  # only 5 dispensed
        ]})
        resp = self.client.post(
            f'/pharmacy/return/{self.bill.pk}/process/',
            data=payload, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_process_return_empty_returns_400(self):
        payload = json.dumps({'returns': []})
        resp = self.client.post(
            f'/pharmacy/return/{self.bill.pk}/process/',
            data=payload, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_process_return_wrong_clinic_returns_404(self):
        other_clinic = _make_clinic('Other Return')
        other_user = _make_user('other_ret')
        _make_staff(other_user, other_clinic)
        c = Client()
        c.login(username='other_ret', password='testpass123')
        payload = json.dumps({'returns': [
            {'dispensed_item_id': self.di.pk, 'return_qty': 1}
        ]})
        resp = c.post(
            f'/pharmacy/return/{self.bill.pk}/process/',
            data=payload, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_process_return_zero_qty_skipped_and_returns_400(self):
        """A return with only return_qty=0 should be treated as no items to return."""
        initial_qty = self.batch.quantity
        payload = json.dumps({'returns': [
            {'dispensed_item_id': self.di.pk, 'return_qty': 0}
        ]})
        resp = self.client.post(
            f'/pharmacy/return/{self.bill.pk}/process/',
            data=payload, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, initial_qty)  # unchanged


# ---------------------------------------------------------------------------
# Bill list view tests
# ---------------------------------------------------------------------------

class BillListViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('billlistdoc')
        self.client.login(username='billlistdoc', password='testpass123')
        from reception.models import Patient, Visit
        from pharmacy.models import PharmacyBill, PharmacyItem, PharmacyBatch, DispensedItem
        from django.utils import timezone as tz
        self.catalog = make_catalog_medicine('Amoxicillin', 'Amoxicillin')
        self.item = PharmacyItem.objects.create(clinic=self.clinic, medicine=self.catalog)
        self.batch = PharmacyBatch.objects.create(
            item=self.item, batch_number='BL001', quantity=100,
            unit_price='12.00',
            expiry_date=tz.now().date() + datetime.timedelta(days=365),
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, full_name='Bill List Patient', phone='9111111111'
        )
        self.visit = Visit.objects.create(
            clinic=self.clinic, patient=self.patient,
            token_number=1, status='done',
        )
        di = DispensedItem.objects.create(
            visit=self.visit, pharmacy_item=self.item, batch=self.batch,
            quantity_dispensed=5, unit_price='12.00', dispensed_by=self.staff,
        )
        self.bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-TEST-0001',
            subtotal='60.00', final_amount='60.00',
        )

    def test_bill_list_loads(self):
        resp = self.client.get('/pharmacy/bills/')
        self.assertEqual(resp.status_code, 200)

    def test_bill_list_shows_bill(self):
        resp = self.client.get('/pharmacy/bills/')
        self.assertContains(resp, 'BILL-TEST-0001')

    def test_bill_list_shows_patient_name(self):
        resp = self.client.get('/pharmacy/bills/')
        self.assertContains(resp, 'Bill List Patient')

    def test_bill_list_shows_amount(self):
        resp = self.client.get('/pharmacy/bills/')
        self.assertContains(resp, '60')

    def test_bill_list_search_by_name(self):
        resp = self.client.get('/pharmacy/bills/?q=Bill+List+Patient')
        self.assertContains(resp, 'BILL-TEST-0001')

    def test_bill_list_search_no_match(self):
        resp = self.client.get('/pharmacy/bills/?q=ZZZNoMatch')
        self.assertNotContains(resp, 'BILL-TEST-0001')

    def test_bill_list_range_7days(self):
        resp = self.client.get('/pharmacy/bills/?range=7')
        self.assertEqual(resp.status_code, 200)

    def test_bill_list_requires_login(self):
        self.client.logout()
        resp = self.client.get('/pharmacy/bills/')
        self.assertEqual(resp.status_code, 302)

    def test_bill_list_clinic_isolation(self):
        """Bills from a different clinic must not appear."""
        other_clinic, other_user, other_staff = make_clinic_and_user('otherbilldoc', 'Other Clinic')
        from reception.models import Patient, Visit
        other_patient = Patient.objects.create(
            clinic=other_clinic, full_name='Other Patient', phone='9888888888'
        )
        other_visit = Visit.objects.create(
            clinic=other_clinic, patient=other_patient, token_number=1, status='done'
        )
        other_bill = PharmacyBill.objects.create(
            visit=other_visit, clinic=other_clinic,
            bill_number='BILL-OTHER-9999',
            subtotal='200.00', final_amount='200.00',
        )
        resp = self.client.get('/pharmacy/bills/')
        self.assertNotContains(resp, 'BILL-OTHER-9999')


# ---------------------------------------------------------------------------
# Pharmacy analytics view tests
# ---------------------------------------------------------------------------

class PharmacyAnalyticsViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('analyticsdoc')
        self.client.login(username='analyticsdoc', password='testpass123')
        from reception.models import Patient, Visit
        from pharmacy.models import PharmacyItem, PharmacyBatch, DispensedItem, PharmacyBill
        from django.utils import timezone as tz
        self.catalog = make_catalog_medicine('Cetirizine', 'Cetirizine HCl')
        self.item = PharmacyItem.objects.create(clinic=self.clinic, medicine=self.catalog)
        self.batch = PharmacyBatch.objects.create(
            item=self.item, batch_number='AN001', quantity=200,
            unit_price='5.00',
            expiry_date=tz.now().date() + datetime.timedelta(days=365),
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, full_name='Analytics Patient', phone='9222222222'
        )
        self.visit = Visit.objects.create(
            clinic=self.clinic, patient=self.patient,
            token_number=1, status='done',
        )
        self.di = DispensedItem.objects.create(
            visit=self.visit, pharmacy_item=self.item, batch=self.batch,
            quantity_dispensed=10, unit_price='5.00', dispensed_by=self.staff,
        )
        self.bill = PharmacyBill.objects.create(
            visit=self.visit, clinic=self.clinic,
            bill_number='BILL-AN-0001',
            subtotal='50.00', final_amount='50.00',
        )

    def test_analytics_loads(self):
        resp = self.client.get('/pharmacy/analytics/')
        self.assertEqual(resp.status_code, 200)

    def test_analytics_shows_revenue(self):
        resp = self.client.get('/pharmacy/analytics/')
        self.assertContains(resp, '50')

    def test_analytics_shows_top_medicine(self):
        resp = self.client.get('/pharmacy/analytics/')
        self.assertContains(resp, 'Cetirizine')

    def test_analytics_shows_bills_count(self):
        resp = self.client.get('/pharmacy/analytics/')
        self.assertContains(resp, '1')  # 1 bill

    def test_analytics_range_7days(self):
        resp = self.client.get('/pharmacy/analytics/?range=7')
        self.assertEqual(resp.status_code, 200)

    def test_analytics_range_90days(self):
        resp = self.client.get('/pharmacy/analytics/?range=90')
        self.assertEqual(resp.status_code, 200)

    def test_analytics_requires_login(self):
        self.client.logout()
        resp = self.client.get('/pharmacy/analytics/')
        self.assertEqual(resp.status_code, 302)

    def test_analytics_no_data_still_loads(self):
        """Analytics should still load even if there are no bills."""
        from pharmacy.models import PharmacyBill, DispensedItem
        DispensedItem.objects.all().delete()
        PharmacyBill.objects.all().delete()
        resp = self.client.get('/pharmacy/analytics/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Analytics')

    def test_analytics_shows_returns(self):
        """If a medicine was returned, it should appear in the returns table."""
        self.di.quantity_returned = 3
        self.di.save()
        resp = self.client.get('/pharmacy/analytics/')
        self.assertContains(resp, 'Returns')


# ---------------------------------------------------------------------------
# Delete patient tests
# ---------------------------------------------------------------------------

class PatientDeleteViewTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('deldoc')
        self.client.login(username='deldoc', password='testpass123')
        from reception.models import Patient
        self.patient = Patient.objects.create(
            clinic=self.clinic, full_name='Delete Me', phone='9333333333'
        )

    def test_delete_page_loads(self):
        resp = self.client.get(f'/patient/{self.patient.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Delete Me')

    def test_delete_without_confirm_shows_error(self):
        resp = self.client.post(f'/patient/{self.patient.id}/delete/', {'confirm': 'WRONG'})
        self.assertEqual(resp.status_code, 200)
        from reception.models import Patient
        self.assertTrue(Patient.objects.filter(id=self.patient.id).exists())

    def test_delete_with_confirm_removes_patient(self):
        resp = self.client.post(f'/patient/{self.patient.id}/delete/', {'confirm': 'DELETE'})
        self.assertEqual(resp.status_code, 302)
        from reception.models import Patient
        self.assertFalse(Patient.objects.filter(id=self.patient.id).exists())

    def test_delete_wrong_clinic_returns_404(self):
        """A doctor from another clinic cannot delete this patient."""
        other_clinic, other_user, _ = make_clinic_and_user('otherdeldoc', 'Other Clinic')
        self.client.logout()
        self.client.login(username='otherdeldoc', password='testpass123')
        resp = self.client.post(f'/patient/{self.patient.id}/delete/', {'confirm': 'DELETE'})
        self.assertEqual(resp.status_code, 404)
        from reception.models import Patient
        self.assertTrue(Patient.objects.filter(id=self.patient.id).exists())

    def test_delete_receptionist_denied(self):
        """Receptionists do not have can_manage_staff and should be denied."""
        recep_user = User.objects.create_user(username='recdeldoc', password='testpass123')
        recep_staff = StaffMember.objects.create(
            clinic=self.clinic, user=recep_user, role='receptionist', display_name='Receptionist'
        )
        set_permissions_from_role(recep_staff)
        recep_staff.save()
        self.client.logout()
        self.client.login(username='recdeldoc', password='testpass123')
        resp = self.client.post(f'/patient/{self.patient.id}/delete/', {'confirm': 'DELETE'})
        self.assertEqual(resp.status_code, 403)
        from reception.models import Patient
        self.assertTrue(Patient.objects.filter(id=self.patient.id).exists())

    def test_delete_requires_login(self):
        self.client.logout()
        resp = self.client.get(f'/patient/{self.patient.id}/delete/')
        self.assertEqual(resp.status_code, 302)

    def test_delete_cascades_visits_and_prescriptions(self):
        """Deleting a patient should cascade-delete their visits and prescriptions."""
        from reception.models import Visit, Patient
        from prescription.models import Prescription
        visit = Visit.objects.create(
            clinic=self.clinic, patient=self.patient, token_number=99, status='done'
        )
        rx = Prescription.objects.create(
            visit=visit, doctor=self.staff,
            raw_clinical_note='test', diagnosis='Test diagnosis',
        )
        resp = self.client.post(f'/patient/{self.patient.id}/delete/', {'confirm': 'DELETE'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Patient.objects.filter(id=self.patient.id).exists())
        self.assertFalse(Visit.objects.filter(id=visit.id).exists())
        self.assertFalse(Prescription.objects.filter(id=rx.id).exists())


# ---------------------------------------------------------------------------
# Injection route (PrescriptionMedicine.route) tests
# ---------------------------------------------------------------------------

class InjectionRouteTest(TestCase):

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('injdoc')
        self.client.login(username='injdoc', password='testpass123')
        from reception.models import Patient, Visit
        self.patient = Patient.objects.create(
            clinic=self.clinic, full_name='Injection Patient', phone='9444444444'
        )
        self.visit = Visit.objects.create(
            clinic=self.clinic, patient=self.patient,
            token_number=1, status='in_consultation',
        )

    def test_save_prescription_with_route(self):
        """Saving a prescription with route='IV' should persist route on PrescriptionMedicine."""
        import json
        from prescription.models import PrescriptionMedicine
        payload = {
            'raw_clinical_note': 'Test injection note',
            'prescription': {
                'soap_note': 'S: test O: test A: test P: test',
                'diagnosis': 'Infection',
                'medicines': [
                    {
                        'drug_name': 'Inj Ceftriaxone 1g',
                        'dosage': '1-0-0',
                        'frequency': 'After meals',
                        'duration': '5 days',
                        'route': 'IV',
                        'notes': '',
                    }
                ],
                'advice': 'Rest',
                'patient_summary_en': '',
                'patient_summary_hi': '',
                'follow_up_days': 7,
                'investigations_text': '',
                'validity_days': 30,
            }
        }
        resp = self.client.post(
            f'/rx/save/{self.visit.id}/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        med = PrescriptionMedicine.objects.get(prescription__visit=self.visit)
        self.assertEqual(med.route, 'IV')
        self.assertEqual(med.drug_name, 'Inj Ceftriaxone 1g')

    def test_save_prescription_without_route_defaults_empty(self):
        """Non-injection medicines should save with empty route."""
        import json
        from prescription.models import PrescriptionMedicine
        payload = {
            'raw_clinical_note': 'Fever, cough',
            'prescription': {
                'soap_note': '',
                'diagnosis': 'URI',
                'medicines': [
                    {
                        'drug_name': 'Tab Paracetamol 500mg',
                        'dosage': '1-1-1',
                        'frequency': 'After meals',
                        'duration': '3 days',
                        'route': '',
                        'notes': 'Take with water',
                    }
                ],
                'advice': '',
                'patient_summary_en': '',
                'patient_summary_hi': '',
                'validity_days': 30,
            }
        }
        resp = self.client.post(
            f'/rx/save/{self.visit.id}/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        med = PrescriptionMedicine.objects.get(prescription__visit=self.visit)
        self.assertEqual(med.route, '')

    def test_route_field_preserved_on_re_save(self):
        """Re-saving a prescription should update route on the medicine."""
        import json
        from prescription.models import PrescriptionMedicine

        def _save(route):
            return self.client.post(
                f'/rx/save/{self.visit.id}/',
                data=json.dumps({
                    'raw_clinical_note': 'note',
                    'prescription': {
                        'soap_note': '', 'diagnosis': 'Sepsis',
                        'medicines': [{
                            'drug_name': 'Inj Meropenem 1g',
                            'dosage': '1-0-0', 'frequency': 'After meals',
                            'duration': '7 days', 'route': route, 'notes': '',
                        }],
                        'advice': '', 'patient_summary_en': '',
                        'patient_summary_hi': '', 'validity_days': 30,
                    }
                }),
                content_type='application/json',
            )

        _save('IV')
        med = PrescriptionMedicine.objects.get(prescription__visit=self.visit)
        self.assertEqual(med.route, 'IV')

        _save('IM')
        # save API deletes and recreates medicines, so re-query
        med = PrescriptionMedicine.objects.get(prescription__visit=self.visit)
        self.assertEqual(med.route, 'IM')

    def test_consult_page_loads_for_done_visit(self):
        """Consult page should be accessible for done visits (for editing)."""
        self.visit.status = 'done'
        self.visit.save()
        resp = self.client.get(f'/rx/consult/{self.visit.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_existing_rx_json_in_context(self):
        """When a prescription exists, existing_rx_json should be in the template context."""
        import json
        from prescription.models import Prescription, PrescriptionMedicine
        rx = Prescription.objects.create(
            visit=self.visit, doctor=self.staff,
            raw_clinical_note='test',
            diagnosis='Test Dx',
        )
        PrescriptionMedicine.objects.create(
            prescription=rx, drug_name='Inj Amikacin 500mg',
            dosage='1-0-0', frequency='After meals',
            duration='5 days', route='IM', notes='', order=0,
        )
        resp = self.client.get(f'/rx/consult/{self.visit.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('existing_rx_json', resp.context)
        rx_data = json.loads(resp.context['existing_rx_json'])
        self.assertEqual(rx_data['diagnosis'], 'Test Dx')
        self.assertEqual(rx_data['medicines'][0]['route'], 'IM')
        self.assertEqual(rx_data['medicines'][0]['drug_name'], 'Inj Amikacin 500mg')


# ---------------------------------------------------------------------------
# Multi-batch dispensing tests
# ---------------------------------------------------------------------------

class MultiBatchDispenseTest(TestCase):
    """
    Tests that dispensing works correctly when qty needed spans multiple batches (FEFO order).
    """

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('multibatch')
        self.patient, self.visit = make_patient_and_visit(self.clinic, 'mb')
        self.client = Client()
        self.client.login(username='multibatch', password='testpass123')

        # Item with TWO batches: batch1 expires sooner (FEFO first), batch2 expires later
        self.item = PharmacyItem.objects.create(
            clinic=self.clinic, custom_name='Amoxicillin 500mg',
            custom_generic_name='Amoxicillin', reorder_level=5,
        )
        self.batch1 = PharmacyBatch.objects.create(
            item=self.item, batch_number='B001',
            expiry_date=today() + datetime.timedelta(days=60),   # expires sooner
            quantity=5, unit_price='10.00',
        )
        self.batch2 = PharmacyBatch.objects.create(
            item=self.item, batch_number='B002',
            expiry_date=today() + datetime.timedelta(days=180),  # expires later
            quantity=20, unit_price='10.00',
        )
        self.confirm_url = f'/pharmacy/dispense/{self.visit.id}/confirm/'

    def _payload(self, qty):
        return json.dumps({
            'items': [{
                'batch_id': self.batch1.pk,  # always send first batch
                'pharmacy_item_id': self.item.pk,
                'prescription_med_id': None,
                'qty': qty,
                'is_substitute': False,
                'notes': '',
            }],
            'discount': 0,
            'payment_mode': 'cash',
        })

    def test_dispense_within_single_batch(self):
        """Qty ≤ batch1 stock: only batch1 used."""
        resp = self.client.post(self.confirm_url, data=self._payload(5), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.batch1.refresh_from_db()
        self.batch2.refresh_from_db()
        self.assertEqual(self.batch1.quantity, 0)   # exhausted
        self.assertEqual(self.batch2.quantity, 20)  # untouched

    def test_dispense_overflows_to_second_batch(self):
        """Qty > batch1 stock: batch1 fully used, remainder from batch2 (FEFO)."""
        # batch1 has 5, batch2 has 20; request 15 → needs both
        resp = self.client.post(self.confirm_url, data=self._payload(15), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        self.batch1.refresh_from_db()
        self.batch2.refresh_from_db()
        self.assertEqual(self.batch1.quantity, 0)   # fully used
        self.assertEqual(self.batch2.quantity, 10)  # 20 - 10 = 10 remaining

    def test_multi_batch_creates_two_dispensed_items(self):
        """When two batches are used, two DispensedItem records are created."""
        self.client.post(self.confirm_url, data=self._payload(15), content_type='application/json')
        di_count = DispensedItem.objects.filter(visit=self.visit).count()
        self.assertEqual(di_count, 2)
        di_b1 = DispensedItem.objects.get(visit=self.visit, batch=self.batch1)
        di_b2 = DispensedItem.objects.get(visit=self.visit, batch=self.batch2)
        self.assertEqual(di_b1.quantity_dispensed, 5)
        self.assertEqual(di_b2.quantity_dispensed, 10)

    def test_dispense_fails_if_total_insufficient(self):
        """Qty > total stock across all batches: 400 error."""
        # batch1=5 + batch2=20 = 25 total; request 30
        resp = self.client.post(self.confirm_url, data=self._payload(30), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])
        self.assertIn('total stock', resp.json()['error'].lower())

    def test_stock_qty_in_dispense_view_shows_total(self):
        """The dispense page should show total stock (sum of batches), not just first batch qty."""
        # batch1=5, batch2=20 → total=25
        from prescription.models import Prescription, PrescriptionMedicine
        rx = Prescription.objects.create(
            visit=self.visit, doctor=self.staff,
            raw_clinical_note='test', diagnosis='Infection',
        )
        PrescriptionMedicine.objects.create(
            prescription=rx, drug_name='Amoxicillin 500mg',
            dosage='1-0-1', frequency='After meals',
            duration='7 days', route='', notes='', order=0,
        )
        resp = self.client.get(f'/pharmacy/dispense/{self.visit.id}/')
        self.assertEqual(resp.status_code, 200)
        rows = resp.context['medicine_rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['stock_qty'], 25)  # total, not just batch1's 5

    def test_single_batch_item_still_works(self):
        """Normal single-batch item dispenses as before."""
        _, single_batch = make_item_with_batch(self.clinic, name='Paracetamol 500mg', qty=50)
        payload = json.dumps({
            'items': [{
                'batch_id': single_batch.pk,
                'pharmacy_item_id': single_batch.item.pk,
                'prescription_med_id': None,
                'qty': 20,
                'is_substitute': False,
                'notes': '',
            }],
            'discount': 0,
            'payment_mode': 'cash',
        })
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        single_batch.refresh_from_db()
        self.assertEqual(single_batch.quantity, 30)

    def test_overflow_batch_with_zero_price_bills_at_first_batch_price(self):
        """
        Regression: if overflow batch has unit_price=0 (added without price),
        the bill must still use the first batch's price — not Rs 0.
        This was the real-world bug: 8 caps billed at Rs 15.90, 2 caps billed at Rs 0.
        """
        # batch1: 8 units at Rs 15.90 (expires sooner — FEFO first)
        # batch2: 20 units at Rs 0.00 (added without price — this is the bug trigger)
        item = PharmacyItem.objects.create(
            clinic=self.clinic, custom_name='Cap Evelife 1gm',
            custom_generic_name='Etoricoxib', reorder_level=5,
        )
        batch1 = PharmacyBatch.objects.create(
            item=item, batch_number='CD-252101D',
            expiry_date=today() + datetime.timedelta(days=60),
            quantity=8, unit_price='15.90',
        )
        PharmacyBatch.objects.create(
            item=item, batch_number='CD-252882B',
            expiry_date=today() + datetime.timedelta(days=180),
            quantity=20, unit_price='0.00',  # the bug: zero price on overflow batch
        )
        # Dispense 10 units (8 from batch1, 2 from batch2)
        payload = json.dumps({
            'items': [{
                'batch_id': batch1.pk,
                'pharmacy_item_id': item.pk,
                'prescription_med_id': None,
                'qty': 10,
                'is_substitute': False,
                'notes': '',
            }],
            'discount': 0,
            'payment_mode': 'cash',
        })
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

        # Bill should be 10 × 15.90 = 159.00 (NOT 8×15.90 + 2×0 = 127.20)
        bill = PharmacyBill.objects.get(visit=self.visit)
        self.assertEqual(bill.subtotal, decimal.Decimal('159.00'))
        self.assertEqual(bill.final_amount, decimal.Decimal('159.00'))

        # Both DispensedItems should have unit_price = 15.90
        dis = DispensedItem.objects.filter(visit=self.visit).order_by('batch__expiry_date')
        self.assertEqual(dis[0].unit_price, decimal.Decimal('15.90'))
        self.assertEqual(dis[1].unit_price, decimal.Decimal('15.90'))



# ===========================================================================
# Zero-price batch fix — 3-layer protection tests
# ===========================================================================


class ZeroPriceLayer3FormValidationTest(TestCase):
    """Layer 3: add_stock, add_batch, edit_batch views must reject unit_price <= 0."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('zp_form')
        self.client = Client()
        self.client.login(username='zp_form', password='testpass123')
        self.med = make_catalog_medicine(name='TestDrug ZP', generic='TestGeneric')
        self.item = PharmacyItem.objects.create(
            clinic=self.clinic, medicine=self.med, reorder_level=5,
        )
        self.batch = PharmacyBatch.objects.create(
            item=self.item, batch_number='ZPBATCH',
            expiry_date=today() + datetime.timedelta(days=90),
            quantity=20, unit_price='5.00',
        )

    # --- add_stock with zero price ---

    def test_add_stock_zero_price_returns_error_not_redirect(self):
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': '',
            'custom_name': 'ZeroMed',
            'batch_number': 'ZB001',
            'quantity': 10,
            'unit_price': '0',
            'reorder_level': 5,
        })
        self.assertEqual(resp.status_code, 200)

    def test_add_stock_zero_price_shows_error_message(self):
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': '',
            'custom_name': 'ZeroMed',
            'batch_number': 'ZB001',
            'quantity': 10,
            'unit_price': '0',
            'reorder_level': 5,
        })
        self.assertContains(resp, 'Unit price')

    def test_add_stock_zero_price_does_not_create_item(self):
        pre_count = PharmacyItem.objects.filter(clinic=self.clinic, custom_name='ZeroMed').count()
        self.client.post('/pharmacy/add/', {
            'catalog_id': '',
            'custom_name': 'ZeroMed',
            'batch_number': 'ZB001',
            'quantity': 10,
            'unit_price': '0',
            'reorder_level': 5,
        })
        self.assertEqual(
            PharmacyItem.objects.filter(clinic=self.clinic, custom_name='ZeroMed').count(),
            pre_count,
        )

    def test_add_stock_valid_price_still_creates_item(self):
        resp = self.client.post('/pharmacy/add/', {
            'catalog_id': '',
            'custom_name': 'ValidMed',
            'batch_number': 'VB001',
            'quantity': 10,
            'unit_price': '12.50',
            'reorder_level': 5,
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.assertTrue(PharmacyItem.objects.filter(clinic=self.clinic, custom_name='ValidMed').exists())

    # --- add_batch with zero price ---

    def test_add_batch_zero_price_returns_error_not_redirect(self):
        resp = self.client.post(f'/pharmacy/item/{self.item.pk}/add-batch/', {
            'batch_number': 'ZBB001',
            'quantity': 15,
            'unit_price': '0',
        })
        self.assertEqual(resp.status_code, 200)

    def test_add_batch_zero_price_shows_error_message(self):
        resp = self.client.post(f'/pharmacy/item/{self.item.pk}/add-batch/', {
            'batch_number': 'ZBB001',
            'quantity': 15,
            'unit_price': '0',
        })
        self.assertContains(resp, 'Unit price')

    def test_add_batch_zero_price_does_not_create_batch(self):
        pre_count = self.item.batches.count()
        self.client.post(f'/pharmacy/item/{self.item.pk}/add-batch/', {
            'batch_number': 'ZBB001',
            'quantity': 15,
            'unit_price': '0',
        })
        self.assertEqual(self.item.batches.count(), pre_count)

    def test_add_batch_valid_price_creates_batch(self):
        pre_count = self.item.batches.count()
        resp = self.client.post(f'/pharmacy/item/{self.item.pk}/add-batch/', {
            'batch_number': 'VBB001',
            'quantity': 15,
            'unit_price': '7.00',
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.assertEqual(self.item.batches.count(), pre_count + 1)

    # --- edit_batch with zero price ---

    def test_edit_batch_zero_price_returns_error_not_redirect(self):
        resp = self.client.post(f'/pharmacy/batch/{self.batch.pk}/edit/', {
            'batch_number': 'EDITED',
            'quantity': 20,
            'unit_price': '0',
        })
        self.assertEqual(resp.status_code, 200)

    def test_edit_batch_zero_price_shows_error_message(self):
        resp = self.client.post(f'/pharmacy/batch/{self.batch.pk}/edit/', {
            'batch_number': 'EDITED',
            'quantity': 20,
            'unit_price': '0',
        })
        self.assertContains(resp, 'Unit price')

    def test_edit_batch_zero_price_does_not_save(self):
        self.client.post(f'/pharmacy/batch/{self.batch.pk}/edit/', {
            'batch_number': 'EDITED',
            'quantity': 20,
            'unit_price': '0',
        })
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.unit_price, decimal.Decimal('5.00'))  # unchanged

    def test_edit_batch_valid_price_saves(self):
        resp = self.client.post(f'/pharmacy/batch/{self.batch.pk}/edit/', {
            'batch_number': 'EDITED',
            'quantity': 20,
            'unit_price': '9.99',
        })
        self.assertRedirects(resp, '/pharmacy/')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.unit_price, decimal.Decimal('9.99'))


class ZeroPriceLayer2DispenseBlockTest(TestCase):
    """Layer 2: confirm_dispense_api must block if billing batch has unit_price=0."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('zp_disp')
        self.patient, self.visit = make_patient_and_visit(self.clinic, 'zpd')
        self.client = Client()
        self.client.login(username='zp_disp', password='testpass123')
        self.confirm_url = f'/pharmacy/dispense/{self.visit.id}/confirm/'

    def _make_zero_price_item(self, name='ZeroPriceMed', qty=50):
        item = PharmacyItem.objects.create(
            clinic=self.clinic, custom_name=name, reorder_level=5,
        )
        batch = PharmacyBatch.objects.create(
            item=item, batch_number='ZP001',
            expiry_date=today() + datetime.timedelta(days=90),
            quantity=qty, unit_price='0.00',
        )
        return item, batch

    def test_confirm_blocked_when_first_fefo_batch_has_zero_price(self):
        item, batch = self._make_zero_price_item()
        payload = json.dumps({
            'items': [{'batch_id': batch.pk, 'qty': 5, 'is_substitute': False, 'notes': ''}],
            'discount': 0,
            'payment_mode': 'cash',
        })
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_confirm_blocked_error_message_mentions_price(self):
        item, batch = self._make_zero_price_item()
        payload = json.dumps({
            'items': [{'batch_id': batch.pk, 'qty': 5, 'is_substitute': False, 'notes': ''}],
            'discount': 0,
            'payment_mode': 'cash',
        })
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        error = resp.json()['error'].lower()
        self.assertIn('price', error)

    def test_confirm_blocked_does_not_create_bill(self):
        item, batch = self._make_zero_price_item()
        payload = json.dumps({
            'items': [{'batch_id': batch.pk, 'qty': 5, 'is_substitute': False, 'notes': ''}],
            'discount': 0,
            'payment_mode': 'cash',
        })
        self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertFalse(PharmacyBill.objects.filter(visit=self.visit).exists())

    def test_confirm_blocked_does_not_decrement_stock(self):
        item, batch = self._make_zero_price_item(qty=50)
        payload = json.dumps({
            'items': [{'batch_id': batch.pk, 'qty': 5, 'is_substitute': False, 'notes': ''}],
            'discount': 0,
            'payment_mode': 'cash',
        })
        self.client.post(self.confirm_url, data=payload, content_type='application/json')
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 50)  # unchanged

    def test_confirm_succeeds_when_first_fefo_has_valid_price(self):
        item = PharmacyItem.objects.create(clinic=self.clinic, custom_name='NormalPriceMed', reorder_level=5)
        batch = PharmacyBatch.objects.create(
            item=item, batch_number='NP001',
            expiry_date=today() + datetime.timedelta(days=90),
            quantity=50, unit_price='10.00',
        )
        payload = json.dumps({
            'items': [{'batch_id': batch.pk, 'qty': 5, 'is_substitute': False, 'notes': ''}],
            'discount': 0,
            'payment_mode': 'cash',
        })
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_overflow_zero_price_second_batch_not_blocked(self):
        """First FEFO batch has valid price; second overflow batch has price=0 → must NOT block."""
        item = PharmacyItem.objects.create(clinic=self.clinic, custom_name='OverflowTest', reorder_level=5)
        first_batch = PharmacyBatch.objects.create(
            item=item, batch_number='OVF-B1',
            expiry_date=today() + datetime.timedelta(days=30),
            quantity=8, unit_price='15.90',
        )
        PharmacyBatch.objects.create(
            item=item, batch_number='OVF-B2',
            expiry_date=today() + datetime.timedelta(days=180),
            quantity=20, unit_price='0.00',
        )
        payload = json.dumps({
            'items': [{'batch_id': first_batch.pk, 'qty': 10, 'is_substitute': False, 'notes': ''}],
            'discount': 0,
            'payment_mode': 'cash',
        })
        resp = self.client.post(self.confirm_url, data=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        bill = PharmacyBill.objects.get(visit=self.visit)
        self.assertEqual(bill.subtotal, decimal.Decimal('159.00'))


class ZeroPriceLayer1DashboardWarningTest(TestCase):
    """Layer 1: pharmacy dashboard exposes zero_price_batches in context and HTML."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('zp_dash')
        self.client = Client()
        self.client.login(username='zp_dash', password='testpass123')

    def _make_batch_with_price(self, price, qty=10, name=None):
        item = PharmacyItem.objects.create(
            clinic=self.clinic, custom_name=name or f'Drug_{price}', reorder_level=5,
        )
        batch = PharmacyBatch.objects.create(
            item=item, batch_number='B1',
            expiry_date=today() + datetime.timedelta(days=90),
            quantity=qty, unit_price=price,
        )
        return item, batch

    def test_zero_price_batches_in_context(self):
        _, zp_batch = self._make_batch_with_price('0.00', name='ZeroDrug')
        resp = self.client.get('/pharmacy/')
        self.assertEqual(resp.status_code, 200)
        zp_batches = resp.context['zero_price_batches']
        self.assertIn(zp_batch.pk, [b.pk for b in zp_batches])

    def test_nonzero_price_batch_not_in_warning_context(self):
        _, good_batch = self._make_batch_with_price('5.00', name='GoodDrug')
        resp = self.client.get('/pharmacy/')
        zp_batches = resp.context['zero_price_batches']
        self.assertNotIn(good_batch.pk, [b.pk for b in zp_batches])

    def test_zero_qty_batch_not_in_warning_context(self):
        _, empty_batch = self._make_batch_with_price('0.00', qty=0, name='EmptyZeroDrug')
        resp = self.client.get('/pharmacy/')
        zp_batches = resp.context['zero_price_batches']
        self.assertNotIn(empty_batch.pk, [b.pk for b in zp_batches])

    def test_warning_card_shown_in_html(self):
        self._make_batch_with_price('0.00', name='HtmlWarnDrug')
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'Set Price')

    def test_warning_card_absent_when_no_zero_price_batches(self):
        self._make_batch_with_price('10.00', name='PricedDrug')
        resp = self.client.get('/pharmacy/')
        self.assertNotContains(resp, 'Set Price')

    def test_warning_shows_medicine_name(self):
        self._make_batch_with_price('0.00', name='AlertMe Drug')
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'AlertMe Drug')

    def test_warning_card_isolates_to_own_clinic(self):
        """Zero-price batches from another clinic must not appear."""
        other_clinic, _, _ = make_clinic_and_user('zp_other', 'Other ZP Clinic')
        other_item = PharmacyItem.objects.create(
            clinic=other_clinic, custom_name='OtherZeroDrug', reorder_level=5,
        )
        other_batch = PharmacyBatch.objects.create(
            item=other_item, batch_number='OZP',
            expiry_date=today() + datetime.timedelta(days=60),
            quantity=10, unit_price='0.00',
        )
        resp = self.client.get('/pharmacy/')
        zp_batches = resp.context['zero_price_batches']
        self.assertNotIn(other_batch.pk, [b.pk for b in zp_batches])

    def test_warning_card_shows_only_5_rows_by_default(self):
        """When > 5 zero-price batches exist, only 5 are visible by default (rest hidden)."""
        for i in range(8):
            item = PharmacyItem.objects.create(
                clinic=self.clinic, custom_name=f'TruncDrug{i}', reorder_level=5,
            )
            PharmacyBatch.objects.create(
                item=item, batch_number=f'T{i}',
                expiry_date=today() + datetime.timedelta(days=90),
                quantity=10, unit_price='0.00',
            )
        resp = self.client.get('/pharmacy/')
        content = resp.content.decode()
        # Toggle button should appear
        self.assertIn('Show all 8', content)
        # Hidden rows marker present
        self.assertIn('zp-row-hidden', content)

    def test_warning_card_no_toggle_when_5_or_fewer(self):
        """5 or fewer zero-price batches — no toggle button rendered."""
        for i in range(3):
            item = PharmacyItem.objects.create(
                clinic=self.clinic, custom_name=f'FewDrug{i}', reorder_level=5,
            )
            PharmacyBatch.objects.create(
                item=item, batch_number=f'F{i}',
                expiry_date=today() + datetime.timedelta(days=90),
                quantity=10, unit_price='0.00',
            )
        resp = self.client.get('/pharmacy/')
        # Context must have ≤5 batches
        self.assertLessEqual(len(resp.context['zero_price_batches']), 5)
        # Toggle button id must not be present in the HTML
        self.assertNotContains(resp, 'id="zp-toggle-btn"')


# ===========================================================================
# GST Billing Tests
# ===========================================================================

class GSTBillingTest(TestCase):
    """Tests for GST calculation in confirm_dispense_api and bill display."""

    def setUp(self):
        self.clinic, self.user, self.staff = make_clinic_and_user('gst_user')
        self.patient, self.visit = make_patient_and_visit(self.clinic, 'gst')
        self.client = Client()
        self.client.login(username='gst_user', password='testpass123')
        self.confirm_url = f'/pharmacy/dispense/{self.visit.id}/confirm/'

        self.item = PharmacyItem.objects.create(
            clinic=self.clinic, custom_name='GSTMed', reorder_level=5,
        )
        self.batch = PharmacyBatch.objects.create(
            item=self.item, batch_number='G001',
            expiry_date=today() + datetime.timedelta(days=90),
            quantity=100, unit_price='100.00',
        )

    def _dispense(self, qty=2, discount=0, gst_percent=None):
        if gst_percent is not None:
            self.clinic.default_gst_percent = decimal.Decimal(str(gst_percent))
            self.clinic.save(update_fields=['default_gst_percent'])
        payload = json.dumps({
            'items': [{'batch_id': self.batch.pk, 'qty': qty, 'is_substitute': False, 'notes': ''}],
            'discount': discount,
            'payment_mode': 'cash',
        })
        return self.client.post(self.confirm_url, data=payload, content_type='application/json')

    def test_no_gst_bill_final_equals_subtotal_minus_discount(self):
        """0% GST: final_amount = subtotal - discount."""
        resp = self._dispense(qty=2, discount=0, gst_percent=0)
        self.assertEqual(resp.status_code, 200)
        bill = PharmacyBill.objects.get(visit=self.visit)
        self.assertEqual(bill.subtotal, decimal.Decimal('200.00'))
        self.assertEqual(bill.gst_percent, decimal.Decimal('0'))
        self.assertEqual(bill.gst_amount, decimal.Decimal('0.00'))
        self.assertEqual(bill.final_amount, decimal.Decimal('200.00'))

    def test_5_percent_gst_calculation(self):
        """5% GST on 200 subtotal → gst_amount=10, final=210."""
        resp = self._dispense(qty=2, discount=0, gst_percent=5)
        self.assertEqual(resp.status_code, 200)
        bill = PharmacyBill.objects.get(visit=self.visit)
        self.assertEqual(bill.gst_percent, decimal.Decimal('5'))
        self.assertEqual(bill.gst_amount, decimal.Decimal('10.00'))
        self.assertEqual(bill.final_amount, decimal.Decimal('210.00'))

    def test_12_percent_gst_calculation(self):
        """12% GST on 200 → gst_amount=24, final=224."""
        resp = self._dispense(qty=2, discount=0, gst_percent=12)
        bill = PharmacyBill.objects.get(visit=self.visit)
        self.assertEqual(bill.gst_amount, decimal.Decimal('24.00'))
        self.assertEqual(bill.final_amount, decimal.Decimal('224.00'))

    def test_gst_applied_after_discount(self):
        """GST is applied on taxable amount (after discount), not on subtotal."""
        # subtotal=200, discount=10%→180 taxable, GST 5%→9, final=189
        resp = self._dispense(qty=2, discount=10, gst_percent=5)
        bill = PharmacyBill.objects.get(visit=self.visit)
        self.assertEqual(bill.subtotal, decimal.Decimal('200.00'))
        self.assertEqual(bill.gst_amount, decimal.Decimal('9.00'))
        self.assertEqual(bill.final_amount, decimal.Decimal('189.00'))

    def test_gst_snapshots_clinic_rate_at_bill_creation(self):
        """Bill stores the GST % at time of creation regardless of later changes."""
        self._dispense(qty=2, discount=0, gst_percent=5)
        # Change clinic GST to 12% after bill created
        self.clinic.default_gst_percent = decimal.Decimal('12')
        self.clinic.save(update_fields=['default_gst_percent'])
        bill = PharmacyBill.objects.get(visit=self.visit)
        # Bill should still reflect 5%
        self.assertEqual(bill.gst_percent, decimal.Decimal('5'))

    def test_gst_number_shown_on_bill_html(self):
        """GSTIN appears in bill HTML when set on clinic."""
        self.clinic.gst_number = '27AABCU9603R1ZX'
        self.clinic.save(update_fields=['gst_number'])
        self._dispense(qty=1, gst_percent=0)
        bill = PharmacyBill.objects.get(visit=self.visit)
        resp = self.client.get(f'/pharmacy/bill/{bill.pk}/')
        self.assertContains(resp, '27AABCU9603R1ZX')

    def test_gst_not_shown_on_bill_when_zero(self):
        """No CGST/SGST rows on bill when GST is 0%."""
        self._dispense(qty=1, gst_percent=0)
        bill = PharmacyBill.objects.get(visit=self.visit)
        resp = self.client.get(f'/pharmacy/bill/{bill.pk}/')
        self.assertNotContains(resp, 'CGST')
        self.assertNotContains(resp, 'SGST')

    def test_cgst_sgst_shown_on_bill_when_gst_nonzero(self):
        """CGST and SGST rows appear on bill when GST > 0%."""
        self._dispense(qty=2, gst_percent=12)
        bill = PharmacyBill.objects.get(visit=self.visit)
        resp = self.client.get(f'/pharmacy/bill/{bill.pk}/')
        self.assertContains(resp, 'CGST')
        self.assertContains(resp, 'SGST')

    def test_clinic_edit_saves_gst_number(self):
        """Saving clinic edit form persists gst_number to DB."""
        resp = self.client.post('/accounts/clinic/edit/', {
            'name': self.clinic.name,
            'address': self.clinic.address,
            'city': self.clinic.city,
            'state': self.clinic.state,
            'phone': self.clinic.phone,
            'drug_license_number': '',
            'medical_license_number': '',
            'gst_number': '29AABCU9603R1ZY',
            'default_gst_percent': '5',
        })
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.gst_number, '29AABCU9603R1ZY')
        self.assertEqual(self.clinic.default_gst_percent, decimal.Decimal('5'))

    def test_clinic_edit_upcases_gst_number(self):
        """gst_number is stored uppercased."""
        self.client.post('/accounts/clinic/edit/', {
            'name': self.clinic.name,
            'address': self.clinic.address,
            'city': self.clinic.city,
            'state': self.clinic.state,
            'phone': self.clinic.phone,
            'drug_license_number': '',
            'medical_license_number': '',
            'gst_number': '29aabcu9603r1zy',
            'default_gst_percent': '0',
        })
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.gst_number, '29AABCU9603R1ZY')


# ---------------------------------------------------------------------------
# Import Medicines feature tests
# ---------------------------------------------------------------------------

class ImportMedicinesViewTest(TestCase):
    """Tests for /pharmacy/import/ — cross-clinic medicine import."""

    def setUp(self):
        # Clinic A — the user's active clinic (target)
        self.clinic_a, self.user, self.staff_a = make_clinic_and_user(
            username='importdoc', clinic_name='Clinic A'
        )
        # Clinic B — another clinic the same user belongs to (source)
        self.clinic_b = Clinic.objects.create(
            name='Clinic B', address='456 Other St', city='Pune', phone='9000000002'
        )
        self.staff_b = StaffMember.objects.create(
            clinic=self.clinic_b, user=self.user, role='admin', display_name='Import Doc'
        )
        set_permissions_from_role(self.staff_b)
        self.staff_b.save()

        # Log in with Clinic A as active clinic
        self.client.login(username='importdoc', password='testpass123')
        session = self.client.session
        session['active_staff_id'] = self.staff_a.pk
        session.save()

        # Catalog medicines
        self.med1 = make_catalog_medicine('Paracetamol', 'Acetaminophen')
        self.med2 = make_catalog_medicine('Amoxicillin', 'Amoxicillin trihydrate')

    # ── GET — single-clinic user is redirected ──────────────────────────────

    def test_single_clinic_user_redirected(self):
        """User with only one clinic gets redirected to dashboard."""
        make_clinic_and_user(username='solouser', clinic_name='Solo Clinic')
        self.client.login(username='solouser', password='testpass123')
        resp = self.client.get('/pharmacy/import/')
        self.assertRedirects(resp, '/pharmacy/', fetch_redirect_response=False)

    # ── GET — preview page renders ──────────────────────────────────────────

    def test_get_no_source_renders_form(self):
        """GET without ?source shows the clinic selector form."""
        resp = self.client.get('/pharmacy/import/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Clinic B')
        self.assertEqual(resp.context['source_items'], [])

    def test_get_with_source_shows_medicines(self):
        """GET ?source=<clinic_b_id> lists medicines from Clinic B."""
        PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med2)
        resp = self.client.get(f'/pharmacy/import/?source={self.clinic_b.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['source_items']), 2)
        self.assertContains(resp, 'Paracetamol')
        self.assertContains(resp, 'Amoxicillin')

    def test_already_imported_medicine_flagged(self):
        """Medicine already in target clinic is flagged already_exists=True."""
        PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        PharmacyItem.objects.create(clinic=self.clinic_a, medicine=self.med1)
        resp = self.client.get(f'/pharmacy/import/?source={self.clinic_b.pk}')
        entry = resp.context['source_items'][0]
        self.assertTrue(entry['already_exists'])

    def test_new_medicine_not_flagged(self):
        """Medicine not yet in target clinic has already_exists=False."""
        PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med2)
        resp = self.client.get(f'/pharmacy/import/?source={self.clinic_b.pk}')
        entry = resp.context['source_items'][0]
        self.assertFalse(entry['already_exists'])

    def test_new_count_correct(self):
        """new_count equals medicines not yet in target clinic."""
        PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med2)
        PharmacyItem.objects.create(clinic=self.clinic_a, medicine=self.med1)
        resp = self.client.get(f'/pharmacy/import/?source={self.clinic_b.pk}')
        self.assertEqual(resp.context['new_count'], 1)

    # ── Custom-name medicine duplicate detection ────────────────────────────

    def test_custom_medicine_not_flagged_when_absent(self):
        """Custom-named medicine absent from target is new."""
        PharmacyItem.objects.create(clinic=self.clinic_b, custom_name='Ayurvedic Churna')
        resp = self.client.get(f'/pharmacy/import/?source={self.clinic_b.pk}')
        entry = resp.context['source_items'][0]
        self.assertFalse(entry['already_exists'])

    def test_custom_medicine_flagged_case_insensitive(self):
        """Same custom name (different case) is detected as duplicate."""
        PharmacyItem.objects.create(clinic=self.clinic_b, custom_name='Ayurvedic Churna')
        PharmacyItem.objects.create(clinic=self.clinic_a, custom_name='ayurvedic churna')
        resp = self.client.get(f'/pharmacy/import/?source={self.clinic_b.pk}')
        entry = resp.context['source_items'][0]
        self.assertTrue(entry['already_exists'])

    # ── POST — successful import ────────────────────────────────────────────

    def test_post_imports_medicines_into_target_clinic(self):
        """POST creates PharmacyItem in target clinic and redirects to dashboard."""
        item_b = PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        resp = self.client.post('/pharmacy/import/', {
            'source': self.clinic_b.pk,
            'items': [item_b.pk],
        })
        self.assertRedirects(resp, '/pharmacy/', fetch_redirect_response=False)
        self.assertTrue(
            PharmacyItem.objects.filter(clinic=self.clinic_a, medicine=self.med1).exists()
        )

    def test_post_copies_reorder_level(self):
        """Imported item inherits reorder_level from source."""
        item_b = PharmacyItem.objects.create(
            clinic=self.clinic_b, medicine=self.med1, reorder_level=25
        )
        self.client.post('/pharmacy/import/', {'source': self.clinic_b.pk, 'items': [item_b.pk]})
        imported = PharmacyItem.objects.get(clinic=self.clinic_a, medicine=self.med1)
        self.assertEqual(imported.reorder_level, 25)

    def test_post_does_not_copy_batches(self):
        """No PharmacyBatch records created in target clinic during import."""
        item_b = PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        PharmacyBatch.objects.create(
            item=item_b, batch_number='B001',
            expiry_date=datetime.date(2026, 12, 31), quantity=100, unit_price=10
        )
        self.client.post('/pharmacy/import/', {'source': self.clinic_b.pk, 'items': [item_b.pk]})
        imported = PharmacyItem.objects.get(clinic=self.clinic_a, medicine=self.med1)
        self.assertEqual(imported.batches.count(), 0)

    def test_post_skips_already_existing_medicine(self):
        """Duplicate medicine is not created twice in target clinic."""
        PharmacyItem.objects.create(clinic=self.clinic_a, medicine=self.med1)
        item_b = PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        self.client.post('/pharmacy/import/', {'source': self.clinic_b.pk, 'items': [item_b.pk]})
        self.assertEqual(
            PharmacyItem.objects.filter(clinic=self.clinic_a, medicine=self.med1).count(), 1
        )

    def test_post_imports_custom_medicine(self):
        """Custom-named medicines are imported with custom_generic_name."""
        item_b = PharmacyItem.objects.create(
            clinic=self.clinic_b, custom_name='Herbal Mix', custom_generic_name='Neem + Tulsi'
        )
        self.client.post('/pharmacy/import/', {'source': self.clinic_b.pk, 'items': [item_b.pk]})
        qs = PharmacyItem.objects.filter(clinic=self.clinic_a, custom_name='Herbal Mix')
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().custom_generic_name, 'Neem + Tulsi')

    def test_post_partial_selection(self):
        """Only selected medicines are imported; unchecked ones are left out."""
        item1 = PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        item2 = PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med2)
        self.client.post('/pharmacy/import/', {'source': self.clinic_b.pk, 'items': [item1.pk]})
        self.assertTrue(PharmacyItem.objects.filter(clinic=self.clinic_a, medicine=self.med1).exists())
        self.assertFalse(PharmacyItem.objects.filter(clinic=self.clinic_a, medicine=self.med2).exists())

    # ── Security ────────────────────────────────────────────────────────────

    def test_cannot_import_from_unowned_clinic(self):
        """POST with clinic the user does not belong to is silently rejected."""
        other_clinic = Clinic.objects.create(
            name='Unrelated Clinic', city='Delhi', phone='9111111111'
        )
        other_item = PharmacyItem.objects.create(clinic=other_clinic, medicine=self.med1)
        resp = self.client.post('/pharmacy/import/', {
            'source': other_clinic.pk,
            'items': [other_item.pk],
        })
        self.assertRedirects(resp, '/pharmacy/', fetch_redirect_response=False)
        self.assertFalse(
            PharmacyItem.objects.filter(clinic=self.clinic_a, medicine=self.med1).exists()
        )

    def test_item_ids_scoped_to_declared_source_clinic(self):
        """Item IDs from a different clinic than source are not imported."""
        item_b = PharmacyItem.objects.create(clinic=self.clinic_b, medicine=self.med1)
        # Declare source=clinic_b but submit an item that doesn't belong there
        other_clinic = Clinic.objects.create(name='Other', city='X', phone='9333333333')
        other_item = PharmacyItem.objects.create(clinic=other_clinic, medicine=self.med2)
        self.client.post('/pharmacy/import/', {
            'source': self.clinic_b.pk,
            'items': [item_b.pk, other_item.pk],  # other_item not from clinic_b
        })
        # med1 imported; med2 NOT (other_item filtered out by clinic=source_clinic)
        self.assertTrue(PharmacyItem.objects.filter(clinic=self.clinic_a, medicine=self.med1).exists())
        self.assertFalse(PharmacyItem.objects.filter(clinic=self.clinic_a, medicine=self.med2).exists())

    # ── Permission guard ────────────────────────────────────────────────────

    def test_requires_can_edit_inventory_permission(self):
        """Receptionist (no inventory permission) cannot access import page."""
        clinic_d = Clinic.objects.create(name='Clinic D', city='Nagpur', phone='9222222222')
        clinic_e = Clinic.objects.create(name='Clinic E', city='Nashik', phone='9222222223')
        recept_user = User.objects.create_user(username='recept1', password='testpass123')
        staff_d = StaffMember.objects.create(
            clinic=clinic_d, user=recept_user, role='receptionist', display_name='R1'
        )
        set_permissions_from_role(staff_d)
        staff_d.save()
        staff_e = StaffMember.objects.create(
            clinic=clinic_e, user=recept_user, role='receptionist', display_name='R1e'
        )
        set_permissions_from_role(staff_e)
        staff_e.save()
        self.assertFalse(staff_d.can_edit_inventory)
        self.client.login(username='recept1', password='testpass123')
        session = self.client.session
        session['active_staff_id'] = staff_d.pk
        session.save()
        resp = self.client.get('/pharmacy/import/')
        self.assertNotEqual(resp.status_code, 200)

    # ── Dashboard button visibility ─────────────────────────────────────────

    def test_import_button_visible_for_multi_clinic_user(self):
        """Import Medicines button appears on pharmacy dashboard for multi-clinic users."""
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'Import Medicines')

    def test_import_button_hidden_for_single_clinic_user(self):
        """Import Medicines button is absent for single-clinic users."""
        make_clinic_and_user(username='singleclinic', clinic_name='Clinic F')
        self.client.login(username='singleclinic', password='testpass123')
        resp = self.client.get('/pharmacy/')
        self.assertNotContains(resp, 'Import Medicines')
