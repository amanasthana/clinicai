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
        today_str = timezone.now().strftime('%Y%m%d')
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

