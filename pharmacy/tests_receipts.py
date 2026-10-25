"""
Parts of one batch can be received on different days, and each part keeps its own date.
(Report: "Fexocare — 17 were in stock, added 100 today, but it shows the old received date.")
"""
import datetime
import json

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from pharmacy.models import PharmacyBatch, PharmacyBill, PharmacyItem, StockReceipt
from pharmacy.tests import _make_clinic, _make_patient, _make_staff, _make_user, _make_visit


@override_settings(DEBUG=False)
class StockReceiptTest(TestCase):
    def setUp(self):
        self.clinic = _make_clinic()
        self.staff = _make_staff(_make_user('rcpt_doc'), self.clinic, role='admin')
        self.client = Client(raise_request_exception=False)
        self.client.login(username='rcpt_doc', password='testpass123')
        self.today = timezone.localdate()
        self.old = self.today - datetime.timedelta(days=12)

    def add(self, qty, batch='FX01', price='12.00', **extra):
        return self.client.post('/pharmacy/add/', {
            'custom_name': 'Fexocare', 'batch_number': batch, 'expiry_date': '2027-06-01',
            'quantity': qty, 'unit_price': price, **extra})

    def backdate_all(self, day):
        StockReceipt.objects.update(received_date=day)
        PharmacyBatch.all_objects.update(received_date=day)

    def test_each_addition_gets_its_own_date(self):
        self.add(17)
        self.backdate_all(self.old)
        self.add(100)
        batch = PharmacyBatch.objects.get()
        self.assertEqual(batch.quantity, 117)
        entries = list(batch.receipts.values_list('quantity', 'received_date'))
        self.assertEqual(entries, [(17, self.old), (100, self.today)])

    def test_ten_small_additions_on_ten_days(self):
        for i in range(10):
            self.add(10)
            StockReceipt.objects.filter(received_date=self.today).update(
                received_date=self.today - datetime.timedelta(days=10 - i))
        batch = PharmacyBatch.objects.get()
        self.assertEqual(batch.quantity, 100)
        dates = list(batch.receipts.values_list('received_date', flat=True))
        self.assertEqual(len(set(dates)), 10)

    def test_add_batch_form_records_entry(self):
        self.add(17)
        item = PharmacyItem.objects.get()
        self.client.post(f'/pharmacy/item/{item.pk}/add-batch/', {
            'batch_number': 'FX01', 'expiry_date': '2027-06-01', 'quantity': 5, 'unit_price': '12.00'})
        self.assertEqual(list(StockReceipt.objects.values_list('quantity', flat=True)), [17, 5])
        self.assertEqual(StockReceipt.objects.last().added_by, self.staff)

    def test_dashboard_lists_entries_with_dates(self):
        self.add(17)
        self.backdate_all(self.old)
        self.add(100)
        resp = self.client.get('/pharmacy/')
        self.assertContains(resp, 'Received:')
        self.assertContains(resp, self.old.strftime('%d %b %Y'))
        self.assertContains(resp, self.today.strftime('%d %b %Y'))

    def test_ledger_counts_top_up_on_the_day_it_came_in(self):
        self.add(17, purchase_price='10.00')
        self.backdate_all(self.today - datetime.timedelta(days=60))   # first part: outside the 30 days
        self.add(100, purchase_price='10.00')
        resp = self.client.get('/pharmacy/ledger/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['purchase_total'], 1000)       # only today's 100 × ₹10
        purchases = [e for e in resp.context['entries'] if e['type'] == 'purchase']
        self.assertEqual([(e['qty'], e['date']) for e in purchases], [(100, self.today)])

    def test_inventory_analytics_uses_entries(self):
        self.add(17, purchase_price='10.00')
        self.backdate_all(self.today - datetime.timedelta(days=60))
        self.add(100, purchase_price='10.00')
        resp = self.client.get('/pharmacy/inventory-analytics/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['purchase_total'], 1000)

    def test_merge_keeps_entries(self):
        a = PharmacyItem.objects.create(clinic=self.clinic, custom_name='Fexocare 120')
        b = PharmacyItem.objects.create(clinic=self.clinic, custom_name='FEXOCARE-120')
        ba = PharmacyBatch.objects.create(item=a, batch_number='F1', quantity=10, unit_price=5)
        bb = PharmacyBatch.objects.create(item=b, batch_number='f1', quantity=7, unit_price=5)
        StockReceipt.objects.create(batch=ba, quantity=10, received_date=self.old)
        StockReceipt.objects.create(batch=bb, quantity=7, received_date=self.today)
        self.client.post(f'/pharmacy/item/{b.pk}/merge/', {'target_id': a.pk})
        ba.refresh_from_db()
        self.assertEqual(ba.quantity, 17)
        self.assertEqual(list(ba.receipts.values_list('quantity', 'received_date')),
                         [(10, self.old), (7, self.today)])

    def test_edit_quantity_does_not_create_entry(self):
        self.add(17)
        b = PharmacyBatch.objects.get()
        self.client.post(f'/pharmacy/batch/{b.pk}/edit/', {
            'batch_number': 'FX01', 'expiry_date': '2027-06-01', 'quantity': '15', 'unit_price': '12.00'})
        self.assertEqual(StockReceipt.objects.count(), 1)


class BackfillStockReceiptsMigrationTest(TransactionTestCase):
    before = [('pharmacy', '0013_stock_receipts')]
    after = [('pharmacy', '0014_backfill_stock_receipts')]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_batches_get_one_entry(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        apps = executor.loader.project_state(self.before).apps
        Item = apps.get_model('pharmacy', 'PharmacyItem')
        Batch = apps.get_model('pharmacy', 'PharmacyBatch')
        Dispensed = apps.get_model('pharmacy', 'DispensedItem')

        clinic = _make_clinic('B')
        visit = _make_visit(_make_patient(clinic, phone='9000000011'), clinic)
        item = Item.objects.create(clinic_id=clinic.pk, custom_name='Fexocare')
        sold_batch = Batch.objects.create(item=item, batch_number='S1', quantity=8, unit_price=5)
        Batch.objects.filter(pk=sold_batch.pk).update(received_date=datetime.date(2026, 9, 1))
        Dispensed.objects.create(visit_id=visit.pk, pharmacy_item=item, batch=sold_batch,
                                 quantity_dispensed=5, quantity_returned=1, unit_price=5)
        Batch.objects.create(item=item, batch_number='Z0', quantity=0, unit_price=5)   # empty, never sold

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        Receipt = executor.loader.project_state(self.after).apps.get_model('pharmacy', 'StockReceipt')
        rows = list(Receipt.objects.values_list('batch_id', 'quantity', 'received_date'))
        self.assertEqual(rows, [(sold_batch.pk, 8 + 5 - 1, datetime.date(2026, 9, 1))])


class BillHistoryTodayTest(TestCase):
    def setUp(self):
        self.clinic = _make_clinic()
        self.staff = _make_staff(_make_user('bill_doc'), self.clinic, role='admin')
        self.client = Client()
        self.client.login(username='bill_doc', password='testpass123')

    def bill(self, number, amount, days_ago, phone):
        visit = _make_visit(_make_patient(self.clinic, phone=phone), self.clinic)
        b = PharmacyBill.objects.create(visit=visit, clinic=self.clinic, bill_number=number,
                                        subtotal=amount, final_amount=amount, created_by=self.staff)
        PharmacyBill.objects.filter(pk=b.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=days_ago))

    def test_today_shows_only_todays_revenue(self):
        self.bill('BILL-A', 150, 0, '9100000001')
        self.bill('BILL-B', 400, 2, '9100000002')
        resp = self.client.get('/pharmacy/bills/?range=1')
        self.assertContains(resp, '>\n          Today\n')
        self.assertEqual(resp.context['total_revenue'], 150)
        self.assertEqual(resp.context['total_bills'], 1)
        self.assertContains(resp, 'Today, ')
        self.assertEqual(self.client.get('/pharmacy/bills/?range=7').context['total_revenue'], 550)

    def test_search_keeps_selected_range(self):
        resp = self.client.get('/pharmacy/bills/?range=1')
        self.assertContains(resp, '<input type="hidden" name="range" value="1">')
