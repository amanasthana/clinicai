"""
Regression tests for:
  1. Deleting old batches/medicines that were already sold → used to 500.
  2. Scanned bills creating the same medicine twice under slightly different names.
  3. Edits with bad input → used to 500.
  4. The same batch number added twice (re-saved scan, double-tap) → medicine shown twice on bills.
"""
import datetime
import decimal
import json

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings

from pharmacy.models import DispensedItem, PharmacyBatch, PharmacyBill, PharmacyItem
from pharmacy.stock import keys_match, name_key, parse_expiry
from pharmacy.tests import (
    _make_clinic, _make_patient, _make_staff, _make_user, _make_visit, make_catalog_medicine,
)

JSON = {'HTTP_ACCEPT': 'application/json'}


@override_settings(DEBUG=False)
class StockTestBase(TestCase):
    def setUp(self):
        self.clinic = _make_clinic()
        self.user = _make_user('stock_doc')
        self.staff = _make_staff(self.user, self.clinic, role='admin')
        self.client = Client(raise_request_exception=False)
        self.client.login(username='stock_doc', password='testpass123')
        self._phone = 9800000000

    def add(self, name, batch='', qty=100, price='5.50', expiry='2027-03-01', json_mode=False, **extra):
        data = {'custom_name': name, 'batch_number': batch, 'expiry_date': expiry,
                'quantity': qty, 'unit_price': price, 'reorder_level': 10, **extra}
        return self.client.post('/pharmacy/add/', data, **(JSON if json_mode else {}))

    def sell(self, batch, qty=2):
        self._phone += 1
        visit = _make_visit(_make_patient(self.clinic, phone=str(self._phone)), self.clinic)
        DispensedItem.objects.create(
            visit=visit, pharmacy_item=batch.item, batch=batch, quantity_dispensed=qty,
            unit_price=batch.unit_price, dispensed_by=self.staff)
        batch.quantity -= qty
        batch.save()
        bill = PharmacyBill.objects.create(
            visit=visit, clinic=self.clinic, bill_number=f'BILL-T-{self._phone}',
            subtotal=batch.unit_price * qty, final_amount=batch.unit_price * qty, created_by=self.staff)
        return bill

    def batch(self, number):
        return PharmacyBatch.all_objects.get(batch_number=number)


# ---------------------------------------------------------------------------
# 1. Deleting sold stock
# ---------------------------------------------------------------------------

class DeleteSoldStockTest(StockTestBase):

    def test_delete_sold_batch_does_not_500(self):
        self.add('Dolo 650', 'OLD01')
        self.add('Dolo 650', 'NEW01')
        b = self.batch('OLD01')
        bill = self.sell(b)
        resp = self.client.post(f'/pharmacy/batch/{b.pk}/delete/')
        self.assertEqual(resp.status_code, 302)
        b.refresh_from_db()
        self.assertTrue(b.is_archived)
        self.assertEqual(b.quantity, 0)
        # Gone from inventory, still on the bill
        self.assertFalse(PharmacyBatch.objects.filter(pk=b.pk).exists())
        self.assertContains(self.client.get('/pharmacy/'), 'removed from inventory')   # flash message
        self.assertNotContains(self.client.get('/pharmacy/'), 'OLD01')
        self.assertContains(self.client.get(f'/pharmacy/bill/{bill.pk}/'), 'OLD01')

    def test_delete_unsold_batch_is_really_deleted(self):
        self.add('Dolo 650', 'A1')
        self.add('Dolo 650', 'A2')
        b = self.batch('A1')
        self.client.post(f'/pharmacy/batch/{b.pk}/delete/')
        self.assertFalse(PharmacyBatch.all_objects.filter(pk=b.pk).exists())

    def test_delete_last_sold_batch_archives_medicine(self):
        self.add('Pan 40', 'P1')
        b = self.batch('P1')
        self.sell(b)
        self.assertEqual(self.client.post(f'/pharmacy/batch/{b.pk}/delete/').status_code, 302)
        item = PharmacyItem.all_objects.get(pk=b.item_id)
        self.assertTrue(item.is_archived)
        self.assertFalse(PharmacyItem.objects.filter(pk=item.pk).exists())

    def test_delete_sold_medicine_does_not_500(self):
        self.add('Azee 500', 'Z1')
        self.add('Azee 500', 'Z2')
        b = self.batch('Z1')
        bill = self.sell(b)
        item = b.item
        resp = self.client.post(f'/pharmacy/item/{item.pk}/delete/')
        self.assertEqual(resp.status_code, 302)
        item = PharmacyItem.all_objects.get(pk=item.pk)
        self.assertTrue(item.is_archived)
        self.assertEqual(PharmacyBatch.objects.filter(item=item).count(), 0)
        # Unsold batch Z2 is really deleted, sold Z1 is kept for the bill
        self.assertFalse(PharmacyBatch.all_objects.filter(batch_number='Z2').exists())
        self.assertTrue(PharmacyBatch.all_objects.filter(batch_number='Z1').exists())
        self.client.get('/pharmacy/')   # shows the "removed" flash message once
        self.assertNotContains(self.client.get('/pharmacy/'), 'Azee 500')
        self.assertEqual(self.client.get(f'/pharmacy/bill/{bill.pk}/').status_code, 200)

    def test_delete_unsold_medicine_is_really_deleted(self):
        self.add('Azee 250', 'Q1')
        item = PharmacyItem.objects.get(custom_name='Azee 250')
        self.client.post(f'/pharmacy/item/{item.pk}/delete/')
        self.assertFalse(PharmacyItem.all_objects.filter(pk=item.pk).exists())

    def test_archived_medicine_hidden_from_search_and_dispense(self):
        self.add('Montair LC', 'M1')
        b = self.batch('M1')
        self.sell(b)
        self.client.post(f'/pharmacy/item/{b.item_id}/delete/')
        self.assertEqual(self.client.get('/pharmacy/api/search/?q=Montair').json()['items'], [])

    def test_restocking_archived_medicine_brings_it_back(self):
        self.add('Montair LC', 'M1')
        b = self.batch('M1')
        self.sell(b)
        self.client.post(f'/pharmacy/item/{b.item_id}/delete/')
        self.add('Montair LC', 'M2', qty=30)
        self.assertEqual(PharmacyItem.all_objects.filter(custom_name='Montair LC').count(), 1)
        item = PharmacyItem.objects.get(custom_name='Montair LC')
        self.assertEqual(item.total_quantity, 30)

    def test_return_to_archived_batch_restores_it(self):
        self.add('Cetzine', 'C1')
        b = self.batch('C1')
        bill = self.sell(b, qty=3)
        self.client.post(f'/pharmacy/item/{b.item_id}/delete/')
        di = DispensedItem.objects.get(batch=b)
        resp = self.client.post(
            f'/pharmacy/return/{bill.pk}/process/',
            json.dumps({'returns': [{'dispensed_item_id': di.pk, 'return_qty': 2}]}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        b.refresh_from_db()
        self.assertFalse(b.is_archived)
        self.assertEqual(b.quantity, 2)
        self.assertFalse(PharmacyItem.all_objects.get(pk=b.item_id).is_archived)

    def test_reverse_bill_on_archived_batch(self):
        self.add('Cetzine', 'C1')
        b = self.batch('C1')
        bill = self.sell(b, qty=3)
        self.client.post(f'/pharmacy/batch/{b.pk}/delete/')
        resp = self.client.post(f'/pharmacy/bill/{bill.pk}/edit/')
        self.assertEqual(resp.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.quantity, 3)
        self.assertFalse(b.is_archived)


# ---------------------------------------------------------------------------
# 2. Duplicate medicines from scanned bills
# ---------------------------------------------------------------------------

class DuplicateMedicineTest(StockTestBase):

    def test_name_variants_go_to_one_medicine(self):
        for name in ('Dolo 650 Tab', 'TAB DOLO-650', 'dolo  650 tablets', 'DOLO 650MG TAB'):
            self.assertEqual(self.add(name, '', json_mode=True).status_code, 200, name)
        self.assertEqual(PharmacyItem.objects.count(), 1)
        self.assertEqual(PharmacyItem.objects.get().total_quantity, 400)

    def test_name_without_form_is_not_put_on_a_specific_form(self):
        self.add('Dolo 650 Syrup')
        self.add('Dolo 650')
        self.assertEqual(PharmacyItem.objects.count(), 2)
        # ...but the doctor is told they may be the same
        self.assertContains(self.client.get('/pharmacy/'), 'may be entered twice')

    def test_different_forms_stay_separate(self):
        self.add('Calpol 250 Tab')
        self.add('Calpol 250 Syrup')
        self.assertEqual(PharmacyItem.objects.count(), 2)

    def test_different_strengths_stay_separate(self):
        self.add('Pan 40')
        self.add('Pan 20')
        self.assertEqual(PharmacyItem.objects.count(), 2)

    def test_ambiguous_name_does_not_guess(self):
        self.add('Calpol 250 Tab')
        self.add('Calpol 250 Syrup')
        self.add('Calpol 250')   # could be either — must not silently pick one
        self.assertEqual(PharmacyItem.objects.count(), 3)

    def test_scanned_name_matches_catalog_medicine(self):
        med = make_catalog_medicine(name='Crocin 500', generic='Paracetamol')
        self.client.post('/pharmacy/add/', {'catalog_id': med.pk, 'quantity': 10, 'unit_price': '2'})
        self.add('CROCIN 500 TABLET', 'CR1')
        self.assertEqual(PharmacyItem.objects.count(), 1)
        self.assertEqual(PharmacyItem.objects.get().total_quantity, 110)

    def test_catalog_add_links_existing_scanned_medicine(self):
        self.add('Crocin 500 Tab', 'CR1')
        med = make_catalog_medicine(name='Crocin 500', generic='Paracetamol')
        self.client.post('/pharmacy/add/', {'catalog_id': med.pk, 'quantity': 10, 'unit_price': '2'})
        item = PharmacyItem.objects.get()
        self.assertEqual(item.medicine_id, med.pk)
        self.assertEqual(item.total_quantity, 110)

    def test_dashboard_flags_existing_duplicates(self):
        # Duplicates created before this fix
        PharmacyItem.objects.create(clinic=self.clinic, custom_name='Augmentin 625')
        PharmacyItem.objects.create(clinic=self.clinic, custom_name='AUGMENTIN-625 TAB')
        self.assertContains(self.client.get('/pharmacy/'), 'may be entered twice')

    def test_merge_moves_stock_and_sales(self):
        a = PharmacyItem.objects.create(clinic=self.clinic, custom_name='Augmentin 625')
        b = PharmacyItem.objects.create(clinic=self.clinic, custom_name='AUGMENTIN-625 TAB')
        PharmacyBatch.objects.create(item=a, batch_number='AG1', quantity=10, unit_price=20)
        bb1 = PharmacyBatch.objects.create(item=b, batch_number='ag1', quantity=5, unit_price=20)
        bb2 = PharmacyBatch.objects.create(item=b, batch_number='AG2', quantity=7, unit_price=20)
        bill = self.sell(bb1, qty=1)

        resp = self.client.post(f'/pharmacy/item/{b.pk}/merge/', {'target_id': a.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PharmacyItem.all_objects.filter(pk=b.pk).exists())
        a.refresh_from_db()
        self.assertEqual(a.total_quantity, 10 + 4 + 7)
        self.assertEqual(sorted(a.batches.values_list('batch_number', flat=True)), ['AG1', 'AG2'])
        di = DispensedItem.objects.get(visit=bill.visit)
        self.assertEqual(di.pharmacy_item_id, a.pk)
        self.assertEqual(di.batch.batch_number, 'AG1')
        self.assertEqual(self.client.get(f'/pharmacy/bill/{bill.pk}/').status_code, 200)
        self.assertFalse(PharmacyBatch.all_objects.filter(pk=bb2.pk, item=b).exists())

    def test_merge_page_suggests_duplicates(self):
        a = PharmacyItem.objects.create(clinic=self.clinic, custom_name='Augmentin 625')
        b = PharmacyItem.objects.create(clinic=self.clinic, custom_name='Augmentin 625 Tab')
        resp = self.client.get(f'/pharmacy/item/{b.pk}/merge/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([o.pk for o in resp.context['suggested']], [a.pk])

    def test_merge_other_clinic_not_allowed(self):
        other = _make_clinic('Other Clinic')
        a = PharmacyItem.objects.create(clinic=other, custom_name='Augmentin 625')
        b = PharmacyItem.objects.create(clinic=self.clinic, custom_name='Augmentin 625')
        resp = self.client.post(f'/pharmacy/item/{b.pk}/merge/', {'target_id': a.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(PharmacyItem.objects.filter(pk=b.pk).exists())

    def test_name_key_rules(self):
        self.assertTrue(keys_match(name_key('Dolo 650'), name_key('TAB. DOLO-650')))
        self.assertFalse(keys_match(name_key('Calpol Tab'), name_key('Calpol Syrup')))
        self.assertFalse(keys_match(name_key('Pan 40'), name_key('Pan D')))


# ---------------------------------------------------------------------------
# 3. Bad input on add / edit shows a message, never a 500
# ---------------------------------------------------------------------------

class InputValidationTest(StockTestBase):

    def setUp(self):
        super().setUp()
        self.add('Pan 40', 'P1')
        self.b = self.batch('P1')
        self.sell(self.b)
        self.base = {'batch_number': 'P1', 'expiry_date': '2027-03-01', 'quantity': '98',
                     'unit_price': '5.50', 'purchase_price': '', 'purchase_gst_percent': ''}

    def edit(self, **changes):
        return self.client.post(f'/pharmacy/batch/{self.b.pk}/edit/', {**self.base, **changes})

    def test_edit_sold_batch_normal(self):
        self.assertEqual(self.edit(quantity='50').status_code, 302)
        self.b.refresh_from_db()
        self.assertEqual(self.b.quantity, 50)

    def test_edit_bad_values_show_error(self):
        cases = {
            'quantity': ['-5', '2.5', 'abc', '99999999999'],
            'unit_price': ['123456789', '-1', 'abc'],
            'batch_number': ['B' * 60],
            'expiry_date': ['31/31/2027'],
            'purchase_gst_percent': ['150'],
        }
        for field, values in cases.items():
            for value in values:
                resp = self.edit(**{field: value})
                self.assertEqual(resp.status_code, 200, f'{field}={value}')
                self.assertContains(resp, 'alert-error', msg_prefix=f'{field}={value}')

    def test_edit_tolerant_values(self):
        self.assertEqual(self.edit(quantity='5.0', unit_price='1,250.50').status_code, 302)
        self.b.refresh_from_db()
        self.assertEqual(self.b.quantity, 5)
        self.assertEqual(self.b.unit_price, decimal.Decimal('1250.50'))

    def test_edit_batch_number_to_existing_one_is_blocked(self):
        self.add('Pan 40', 'P2')
        resp = self.edit(batch_number='p2 ')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')

    def test_edit_item_bad_values(self):
        item = self.b.item
        for data in ({'custom_name': 'x', 'reorder_level': '-1'},
                     {'custom_name': 'N' * 260, 'reorder_level': '10'}):
            resp = self.client.post(f'/pharmacy/item/{item.pk}/edit/', data)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'alert-error')

    def test_scan_save_bad_expiry_returns_json_error(self):
        resp = self.add('Azee 500', 'A1', expiry='31/31/2027', json_mode=True)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Expiry', resp.json()['error'])

    def test_scan_save_zero_price_is_reported_not_silently_dropped(self):
        resp = self.add('Azee 500', 'A1', price='0', json_mode=True)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_scan_save_month_expiry_formats(self):
        for i, exp in enumerate(('03/2027', '2027-03', '03-2027', 'Mar-27', '03/27')):
            resp = self.add('Azee 500', f'E{i}', expiry=exp, json_mode=True)
            self.assertEqual(resp.status_code, 200, exp)
            self.assertEqual(self.batch(f'E{i}').expiry_date, datetime.date(2027, 3, 1), exp)

    def test_parse_expiry_full_dates(self):
        self.assertEqual(parse_expiry('2027-03-15'), datetime.date(2027, 3, 15))
        self.assertEqual(parse_expiry('15/03/2027'), datetime.date(2027, 3, 15))
        self.assertIsNone(parse_expiry(''))


# ---------------------------------------------------------------------------
# 4. Same batch number added twice
# ---------------------------------------------------------------------------

class DuplicateBatchTest(StockTestBase):

    def test_resaving_scanned_bill_tops_up_instead_of_duplicating(self):
        r1 = self.add('Dolo 650', 'X1', qty=100, json_mode=True)
        r2 = self.add('Dolo 650', 'X1', qty=100, json_mode=True)
        self.assertFalse(r1.json()['merged'])
        self.assertTrue(r2.json()['merged'])
        self.assertEqual(PharmacyBatch.objects.filter(batch_number='X1').count(), 1)
        self.assertEqual(self.batch('X1').quantity, 200)

    def test_batch_number_match_ignores_case_and_spaces(self):
        self.add('Dolo 650', 'ab12')
        self.add('Dolo 650', ' AB12 ')
        self.assertEqual(PharmacyBatch.objects.count(), 1)

    def test_add_batch_form_tops_up(self):
        self.add('Dolo 650', 'X1', qty=10)
        item = PharmacyItem.objects.get()
        resp = self.client.post(f'/pharmacy/item/{item.pk}/add-batch/', {
            'batch_number': 'X1', 'expiry_date': '2027-03-01', 'quantity': 5, 'unit_price': '6.00'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(item.batches.count(), 1)
        b = item.batches.get()
        self.assertEqual(b.quantity, 15)
        self.assertEqual(b.unit_price, decimal.Decimal('6.00'))   # latest MRP wins

    def test_blank_batch_numbers_may_repeat(self):
        self.add('Dolo 650', '')
        self.add('Dolo 650', '')
        self.assertEqual(PharmacyBatch.objects.count(), 2)

    def test_same_batch_number_allowed_on_different_medicines(self):
        self.add('Dolo 650', 'X1')
        self.add('Pan 40', 'X1')
        self.assertEqual(PharmacyBatch.objects.filter(batch_number='X1').count(), 2)

    def test_restocking_archived_batch_revives_it(self):
        self.add('Dolo 650', 'X1')
        self.add('Dolo 650', 'X2')
        b = self.batch('X1')
        self.sell(b)
        self.client.post(f'/pharmacy/batch/{b.pk}/delete/')
        self.add('Dolo 650', 'X1', qty=40)
        b.refresh_from_db()
        self.assertFalse(b.is_archived)
        self.assertEqual(b.quantity, 40)

    def test_database_rejects_duplicate_batch_number(self):
        self.add('Dolo 650', 'X1')
        item = PharmacyItem.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PharmacyBatch.objects.create(item=item, batch_number='x1', quantity=1, unit_price=1)

    def test_stock_check_api_warns_about_existing_batch(self):
        self.add('Dolo 650', 'X1', qty=100)
        resp = self.client.post('/pharmacy/api/stock-check/', json.dumps({'items': [
            {'name': 'DOLO-650', 'batch_number': 'x1'},
            {'name': 'Dolo 650', 'batch_number': 'NEW'},
            {'name': 'Brand New', 'batch_number': 'X1'},
        ]}), content_type='application/json')
        items = resp.json()['items']
        self.assertEqual(items[0], {'item_name': 'Dolo 650', 'batch_quantity': 100})
        self.assertEqual(items[1], {'item_name': 'Dolo 650', 'batch_quantity': None})
        self.assertEqual(items[2], {'item_name': None, 'batch_quantity': None})


class DispenseTest(StockTestBase):

    def _dispense(self, visit, items):
        return self.client.post(f'/pharmacy/dispense/{visit.id}/confirm/',
                                json.dumps({'items': items}), content_type='application/json')

    def test_same_medicine_twice_cannot_oversell(self):
        self.add('Dolo 650', 'X1', qty=5)
        b = self.batch('X1')
        visit = _make_visit(_make_patient(self.clinic, phone='9811111111'), self.clinic)
        resp = self._dispense(visit, [{'batch_id': b.pk, 'qty': 3}, {'batch_id': b.pk, 'qty': 3}])
        self.assertEqual(resp.status_code, 400)
        b.refresh_from_db()
        self.assertEqual(b.quantity, 5)
        self.assertFalse(PharmacyBill.objects.filter(visit=visit).exists())

    def test_second_confirm_does_not_bill_twice(self):
        self.add('Dolo 650', 'X1', qty=50)
        b = self.batch('X1')
        visit = _make_visit(_make_patient(self.clinic, phone='9811111112'), self.clinic)
        self.assertEqual(self._dispense(visit, [{'batch_id': b.pk, 'qty': 2}]).status_code, 200)
        self.assertEqual(self._dispense(visit, [{'batch_id': b.pk, 'qty': 2}]).status_code, 400)
        b.refresh_from_db()
        self.assertEqual(b.quantity, 48)

    def test_bill_shows_one_line_per_batch(self):
        # Older bills can hold two rows for the same batch (from before duplicate batches were merged)
        self.add('Dolo 650', 'X1', qty=50)
        b = self.batch('X1')
        bill = self.sell(b, qty=2)
        DispensedItem.objects.create(visit=bill.visit, pharmacy_item=b.item, batch=b,
                                     quantity_dispensed=3, unit_price=b.unit_price, dispensed_by=self.staff)
        resp = self.client.get(f'/pharmacy/bill/{bill.pk}/')
        lines = resp.context['dispensed_items']
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].quantity_dispensed, 5)


# ---------------------------------------------------------------------------
# Data migration: existing duplicate batches in production are combined
# ---------------------------------------------------------------------------

class MergeDuplicateBatchesMigrationTest(TransactionTestCase):
    before = [('pharmacy', '0010_archive_flags')]
    after = [('pharmacy', '0012_batch_number_unique_per_item')]

    def tearDown(self):
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_duplicates_are_combined_and_sales_repointed(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        apps = executor.loader.project_state(self.before).apps
        Item = apps.get_model('pharmacy', 'PharmacyItem')
        Batch = apps.get_model('pharmacy', 'PharmacyBatch')
        Dispensed = apps.get_model('pharmacy', 'DispensedItem')

        # Tables outside pharmacy are untouched by these migrations — use the current models
        clinic = _make_clinic('M')
        visit = _make_visit(_make_patient(clinic, phone='9000000010'), clinic)
        item = Item.objects.create(clinic_id=clinic.pk, custom_name='Dolo 650')
        b1 = Batch.objects.create(item=item, batch_number='X1', quantity=40, unit_price=5)
        b2 = Batch.objects.create(item=item, batch_number='x1 ', quantity=60, unit_price=6,
                                  expiry_date=datetime.date(2027, 3, 1))
        Batch.objects.create(item=item, batch_number='', quantity=1, unit_price=5)
        Batch.objects.create(item=item, batch_number='', quantity=1, unit_price=5)
        d = Dispensed.objects.create(visit_id=visit.pk, pharmacy_item=item, batch=b2,
                                     quantity_dispensed=1, unit_price=6)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        apps = executor.loader.project_state(self.after).apps
        Batch = apps.get_model('pharmacy', 'PharmacyBatch')
        Dispensed = apps.get_model('pharmacy', 'DispensedItem')

        merged = Batch.objects.get(item_id=item.pk, batch_number='X1')
        self.assertEqual(merged.pk, b1.pk)
        self.assertEqual(merged.quantity, 100)
        self.assertEqual(merged.unit_price, 6)
        self.assertEqual(merged.expiry_date, datetime.date(2027, 3, 1))
        self.assertEqual(Batch.objects.filter(item_id=item.pk, batch_number='').count(), 2)
        self.assertEqual(Dispensed.objects.get(pk=d.pk).batch_id, b1.pk)
