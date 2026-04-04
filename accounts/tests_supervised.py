"""
Comprehensive tests for the supervised action (maker-checker) system.

Covers:
  - Model: SupervisedActionRequest.to_dict(), is_pending_expired
  - API views: request, poll, cancel, pending_count, pending_actions,
               resolve (approve/deny), bulk_resolve
  - Executors: bill_reversal, medicine_return, queue_delete
  - Supervisor log view
  - Access control: non-supervisors cannot approve/view
  - Edge cases: double-approve, cancel-then-approve, bad payload,
                return-more-than-dispensed, delete-visit-with-prescription
"""
import json
import uuid
import decimal
from datetime import date

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import Clinic, StaffMember, SupervisedActionRequest
from reception.models import Patient, Visit
from pharmacy.models import PharmacyItem, PharmacyBatch, DispensedItem, PharmacyBill

User = get_user_model()


# ── Shared fixture helpers ──────────────────────────────────────────────────

def make_clinic(name='Test Clinic'):
    return Clinic.objects.create(name=name, city='Mumbai')


def make_user(username):
    return User.objects.create_user(username=username, password='pass')


def make_staff(user, clinic, role, display_name='Staff'):
    perms = {}
    if role == 'doctor':
        perms = dict(can_register_patients=True, can_prescribe=True,
                     can_view_pharmacy=True, can_view_analytics=True)
    elif role == 'admin':
        perms = dict(can_register_patients=True, can_manage_staff=True,
                     can_view_analytics=True)
    elif role == 'pharmacist':
        perms = dict(can_view_pharmacy=True, can_dispense_bill=True,
                     can_edit_inventory=True)
    elif role == 'receptionist':
        perms = dict(can_register_patients=True)
    return StaffMember.objects.create(
        user=user, clinic=clinic, role=role,
        display_name=display_name, **perms
    )


def make_supervised_request(clinic, user, staff_member, action_type='queue_delete',
                             payload=None, description='Test action'):
    return SupervisedActionRequest.objects.create(
        clinic=clinic,
        action_type=action_type,
        requested_by=user,
        requester_name=staff_member.display_name,
        description=description,
        action_payload=payload or {},
    )


def make_patient(clinic):
    return Patient.objects.create(
        clinic=clinic, full_name='Ramesh Kumar', phone='9000000001'
    )


def make_visit(patient, clinic):
    return Visit.objects.create(
        patient=patient, clinic=clinic, token_number=1
    )


def make_pharmacy_item(clinic, name='Paracetamol 500mg'):
    return PharmacyItem.objects.create(clinic=clinic, custom_name=name)


def make_batch(item, qty=100, unit_price=decimal.Decimal('5.00')):
    return PharmacyBatch.objects.create(
        item=item, quantity=qty, unit_price=unit_price,
        expiry_date=date(2030, 1, 1)
    )


def make_bill(visit, clinic, item, batch, qty=10, unit_price=decimal.Decimal('5.00')):
    """Create a bill with one dispensed item."""
    di = DispensedItem.objects.create(
        visit=visit,
        pharmacy_item=item,
        batch=batch,
        quantity_dispensed=qty,
        unit_price=unit_price,
    )
    bill = PharmacyBill.objects.create(
        visit=visit, clinic=clinic,
        bill_number=f'BILL-TEST-{uuid.uuid4().hex[:6].upper()}',
        subtotal=unit_price * qty,
        final_amount=unit_price * qty,
    )
    return bill, di


# ── Base test class ─────────────────────────────────────────────────────────

class SupervisedBase(TestCase):
    def setUp(self):
        self.clinic = make_clinic()
        # Doctor (supervisor)
        self.doc_user = make_user('doc')
        self.doc_sm = make_staff(self.doc_user, self.clinic, 'doctor', 'Dr. Test')
        # Admin (supervisor)
        self.admin_user = make_user('adm')
        self.admin_sm = make_staff(self.admin_user, self.clinic, 'admin', 'Admin Test')
        # Receptionist (staff, not supervisor)
        self.rec_user = make_user('rec')
        self.rec_sm = make_staff(self.rec_user, self.clinic, 'receptionist', 'Reception')
        # Pharmacist (staff)
        self.ph_user = make_user('ph')
        self.ph_sm = make_staff(self.ph_user, self.clinic, 'pharmacist', 'Pharmacist')

        self.client = Client()

    def login(self, user):
        self.client.force_login(user)

    def post_json(self, url, data):
        return self.client.post(
            url, json.dumps(data), content_type='application/json'
        )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Model tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisedRequestModel(SupervisedBase):

    def test_to_dict_no_crash_when_expires_at_is_none(self):
        """to_dict() must not raise when expires_at is None (the normal case)."""
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            payload={'visit_id': str(uuid.uuid4())}
        )
        self.assertIsNone(req.expires_at)
        d = req.to_dict()   # must not raise
        self.assertEqual(d['status'], 'pending')
        self.assertIn('time_ago', d)
        self.assertIn('detail_items', d)

    def test_to_dict_contains_required_js_keys(self):
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            description='Delete visit',
            payload={'visit_id': 'abc', 'detail_lines': ['Patient: Ramesh', 'Token: #3']}
        )
        d = req.to_dict()
        for key in ('id', 'action_type', 'description', 'patient_name',
                    'amount', 'reference', 'requester_name', 'staff_note',
                    'detail_items', 'status', 'denial_reason',
                    'failure_detail', 'time_ago', 'created_at'):
            self.assertIn(key, d, f"Key '{key}' missing from to_dict()")

    def test_to_dict_detail_items_from_payload(self):
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            payload={'detail_lines': ['Line A', 'Line B']}
        )
        d = req.to_dict()
        self.assertEqual(d['detail_items'], ['Line A', 'Line B'])

    def test_to_dict_detail_items_empty_when_missing(self):
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            payload={}
        )
        d = req.to_dict()
        self.assertEqual(d['detail_items'], [])

    def test_is_pending_expired_always_false(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.assertFalse(req.is_pending_expired)

    def test_str_representation(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.assertIn('pending', str(req))


# ══════════════════════════════════════════════════════════════════════════════
# 2. request_action_api
# ══════════════════════════════════════════════════════════════════════════════

class TestRequestActionApi(SupervisedBase):

    def _url(self):
        return reverse('accounts:supervised_request')

    def test_create_queue_delete_request(self):
        self.login(self.rec_user)
        resp = self.post_json(self._url(), {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': str(uuid.uuid4())},
            'description': 'Remove test patient',
            'patient_name': 'Ramesh Kumar',
            'reference': 'Token #5',
            'detail_items': ['Patient: Ramesh Kumar', 'Token: #5'],
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        req = SupervisedActionRequest.objects.get(id=data['request_id'])
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.action_type, 'queue_delete')
        self.assertEqual(req.action_payload.get('detail_lines'),
                         ['Patient: Ramesh Kumar', 'Token: #5'])

    def test_detail_items_stored_in_payload(self):
        self.login(self.rec_user)
        resp = self.post_json(self._url(), {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': '1'},
            'description': 'x',
            'detail_items': ['Item A', 'Item B'],
        })
        data = resp.json()
        req = SupervisedActionRequest.objects.get(id=data['request_id'])
        self.assertEqual(req.action_payload.get('detail_lines'), ['Item A', 'Item B'])

    def test_detail_items_stripped_to_30(self):
        self.login(self.rec_user)
        resp = self.post_json(self._url(), {
            'action_type': 'queue_delete',
            'action_payload': {},
            'description': 'x',
            'detail_items': [f'Item {i}' for i in range(50)],
        })
        data = resp.json()
        req = SupervisedActionRequest.objects.get(id=data['request_id'])
        self.assertEqual(len(req.action_payload.get('detail_lines', [])), 30)

    def test_invalid_action_type_rejected(self):
        self.login(self.rec_user)
        resp = self.post_json(self._url(), {
            'action_type': 'delete_everything',
            'action_payload': {},
            'description': 'x',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_unauthenticated_rejected(self):
        resp = self.post_json(self._url(), {
            'action_type': 'queue_delete', 'action_payload': {}, 'description': 'x'
        })
        self.assertIn(resp.status_code, [302, 403])

    def test_amount_stored_as_decimal(self):
        self.login(self.rec_user)
        resp = self.post_json(self._url(), {
            'action_type': 'bill_reversal',
            'action_payload': {'bill_id': 1},
            'description': 'Reverse bill',
            'amount': '250.50',
        })
        data = resp.json()
        req = SupervisedActionRequest.objects.get(id=data['request_id'])
        self.assertEqual(req.amount, decimal.Decimal('250.50'))


# ══════════════════════════════════════════════════════════════════════════════
# 3. poll_action_api
# ══════════════════════════════════════════════════════════════════════════════

class TestPollActionApi(SupervisedBase):

    def _url(self, request_id):
        return reverse('accounts:supervised_poll', args=[request_id])

    def test_poll_pending_no_crash(self):
        self.login(self.rec_user)
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        resp = self.client.get(self._url(req.id))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'pending')
        # Must NOT contain expires_in_minutes (removed)
        self.assertNotIn('expires_in_minutes', data)

    def test_poll_approved_contains_redirect(self):
        self.login(self.rec_user)
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req.status = 'approved'
        req.result_data = {'redirect': '/pharmacy/bill/1/'}
        req.save()
        resp = self.client.get(self._url(req.id))
        data = resp.json()
        self.assertEqual(data['status'], 'approved')
        self.assertEqual(data['redirect'], '/pharmacy/bill/1/')

    def test_poll_denied_contains_reason(self):
        self.login(self.rec_user)
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req.status = 'denied'
        req.denial_reason = 'Not authorized'
        req.save()
        resp = self.client.get(self._url(req.id))
        data = resp.json()
        self.assertEqual(data['status'], 'denied')
        self.assertEqual(data['denial_reason'], 'Not authorized')

    def test_poll_wrong_clinic_blocked(self):
        other_clinic = make_clinic('Other Clinic')
        other_user = make_user('other')
        make_staff(other_user, other_clinic, 'receptionist')
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(other_user)
        resp = self.client.get(self._url(req.id))
        self.assertEqual(resp.status_code, 404)

    def test_poll_not_own_request_but_same_clinic_visible(self):
        """Any staff in the same clinic can poll any request (for shared screens)."""
        self.login(self.ph_user)
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        resp = self.client.get(self._url(req.id))
        self.assertEqual(resp.status_code, 200)


# ══════════════════════════════════════════════════════════════════════════════
# 4. cancel_action_api
# ══════════════════════════════════════════════════════════════════════════════

class TestCancelActionApi(SupervisedBase):

    def _url(self, request_id):
        return reverse('accounts:supervised_cancel', args=[request_id])

    def test_staff_can_cancel_own_pending_request(self):
        self.login(self.rec_user)
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        resp = self.post_json(self._url(req.id), {})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'cancelled')

    def test_cannot_cancel_another_staffs_request(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(self.ph_user)
        resp = self.post_json(self._url(req.id), {})
        self.assertEqual(resp.status_code, 404)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

    def test_cannot_cancel_already_approved_request(self):
        self.login(self.rec_user)
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req.status = 'approved'
        req.save()
        resp = self.post_json(self._url(req.id), {})
        self.assertEqual(resp.status_code, 404)


# ══════════════════════════════════════════════════════════════════════════════
# 5. pending_count_api
# ══════════════════════════════════════════════════════════════════════════════

class TestPendingCountApi(SupervisedBase):

    def _url(self):
        return reverse('accounts:supervised_count')

    def test_supervisor_sees_count(self):
        make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.json()['count'], 2)

    def test_admin_also_sees_count(self):
        make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(self.admin_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.json()['count'], 1)

    def test_non_supervisor_sees_zero(self):
        make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(self.rec_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.json()['count'], 0)

    def test_count_excludes_resolved(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req.status = 'approved'
        req.save()
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.json()['count'], 0)


# ══════════════════════════════════════════════════════════════════════════════
# 6. pending_actions_api
# ══════════════════════════════════════════════════════════════════════════════

class TestPendingActionsApi(SupervisedBase):

    def _url(self):
        return reverse('accounts:supervised_pending_api')

    def test_returns_grouped_by_action_type(self):
        make_supervised_request(self.clinic, self.rec_user, self.rec_sm,
                                action_type='queue_delete')
        make_supervised_request(self.clinic, self.rec_user, self.rec_sm,
                                action_type='queue_delete')
        make_supervised_request(self.clinic, self.ph_user, self.ph_sm,
                                action_type='bill_reversal')
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['total'], 3)
        types = {g['action_type'] for g in data['groups']}
        self.assertIn('queue_delete', types)
        self.assertIn('bill_reversal', types)

    def test_group_count_correct(self):
        for _ in range(3):
            make_supervised_request(self.clinic, self.rec_user, self.rec_sm,
                                    action_type='medicine_return')
        self.login(self.doc_user)
        data = self.client.get(self._url()).json()
        group = next(g for g in data['groups'] if g['action_type'] == 'medicine_return')
        self.assertEqual(group['count'], 3)

    def test_items_contain_detail_items(self):
        make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            payload={'visit_id': 'x', 'detail_lines': ['Patient: A', 'Token: #1']}
        )
        self.login(self.doc_user)
        data = self.client.get(self._url()).json()
        item = data['groups'][0]['items'][0]
        self.assertEqual(item['detail_items'], ['Patient: A', 'Token: #1'])

    def test_non_supervisor_blocked(self):
        self.login(self.rec_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403)

    def test_no_crash_with_zero_pending(self):
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['groups'], [])


# ══════════════════════════════════════════════════════════════════════════════
# 7. resolve_action_api (approve / deny single)
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveActionApi(SupervisedBase):

    def _url(self, request_id):
        return reverse('accounts:supervised_resolve', args=[request_id])

    def test_doctor_can_deny(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(self.doc_user)
        resp = self.post_json(self._url(req.id), {
            'decision': 'deny', 'denial_reason': 'Not needed'
        })
        self.assertTrue(resp.json()['ok'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'denied')
        self.assertEqual(req.denial_reason, 'Not needed')
        self.assertEqual(req.resolved_by, self.doc_user)

    def test_admin_can_deny(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(self.admin_user)
        resp = self.post_json(self._url(req.id), {'decision': 'deny'})
        self.assertTrue(resp.json()['ok'])
        req.refresh_from_db()
        self.assertEqual(req.resolved_by, self.admin_user)

    def test_receptionist_cannot_resolve(self):
        req = make_supervised_request(self.clinic, self.ph_user, self.ph_sm)
        self.login(self.rec_user)
        resp = self.post_json(self._url(req.id), {'decision': 'approve'})
        self.assertEqual(resp.status_code, 403)

    def test_cannot_resolve_already_resolved(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req.status = 'denied'
        req.save()
        self.login(self.doc_user)
        resp = self.post_json(self._url(req.id), {'decision': 'approve'})
        self.assertEqual(resp.status_code, 409)

    def test_invalid_decision_rejected(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(self.doc_user)
        resp = self.post_json(self._url(req.id), {'decision': 'maybe'})
        self.assertEqual(resp.status_code, 400)

    def test_wrong_clinic_cannot_resolve(self):
        other_clinic = make_clinic('Other')
        other_doc = make_user('odoc')
        make_staff(other_doc, other_clinic, 'doctor', 'Other Doc')
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self.login(other_doc)
        resp = self.post_json(self._url(req.id), {'decision': 'deny'})
        self.assertEqual(resp.status_code, 404)


# ══════════════════════════════════════════════════════════════════════════════
# 8. bulk_resolve_api
# ══════════════════════════════════════════════════════════════════════════════

class TestBulkResolveApi(SupervisedBase):

    def _url(self):
        return reverse('accounts:supervised_bulk_resolve')

    def _make_reqs(self, n=3):
        return [
            make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
            for _ in range(n)
        ]

    def test_bulk_deny(self):
        reqs = self._make_reqs(3)
        ids = [str(r.id) for r in reqs]
        self.login(self.doc_user)
        resp = self.post_json(self._url(), {
            'request_ids': ids, 'decision': 'deny', 'denial_reason': 'Bulk deny'
        })
        self.assertTrue(resp.json()['ok'])
        for req in reqs:
            req.refresh_from_db()
            self.assertEqual(req.status, 'denied')
            self.assertEqual(req.denial_reason, 'Bulk deny')
            self.assertEqual(req.resolved_by, self.doc_user)

    def test_bulk_deny_ignores_other_clinic_requests(self):
        other_clinic = make_clinic('Other')
        other_user = make_user('ou2')
        other_sm = make_staff(other_user, other_clinic, 'receptionist', 'Other')
        other_req = make_supervised_request(other_clinic, other_user, other_sm)

        self.login(self.doc_user)
        resp = self.post_json(self._url(), {
            'request_ids': [str(other_req.id)], 'decision': 'deny'
        })
        # Returns ok=True but 0 results processed (wrong clinic filtered out)
        data = resp.json()
        self.assertTrue(data['ok'])
        other_req.refresh_from_db()
        self.assertEqual(other_req.status, 'pending')  # untouched

    def test_empty_ids_rejected(self):
        self.login(self.doc_user)
        resp = self.post_json(self._url(), {'request_ids': [], 'decision': 'deny'})
        self.assertEqual(resp.status_code, 400)

    def test_non_supervisor_blocked(self):
        reqs = self._make_reqs(1)
        self.login(self.rec_user)
        resp = self.post_json(self._url(), {
            'request_ids': [str(reqs[0].id)], 'decision': 'deny'
        })
        self.assertEqual(resp.status_code, 403)

    def test_bulk_skips_already_resolved(self):
        req1 = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req2 = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req2.status = 'approved'
        req2.save()
        self.login(self.doc_user)
        resp = self.post_json(self._url(), {
            'request_ids': [str(req1.id), str(req2.id)], 'decision': 'deny'
        })
        data = resp.json()
        self.assertTrue(data['ok'])
        # Only req1 should be in results (req2 was not pending)
        result_ids = [r['id'] for r in data['results']]
        self.assertIn(str(req1.id), result_ids)
        self.assertNotIn(str(req2.id), result_ids)
        req2.refresh_from_db()
        self.assertEqual(req2.status, 'approved')  # unchanged


# ══════════════════════════════════════════════════════════════════════════════
# 9. Executor: queue_delete
# ══════════════════════════════════════════════════════════════════════════════

class TestQueueDeleteExecutor(SupervisedBase):

    def _resolve_url(self, request_id):
        return reverse('accounts:supervised_resolve', args=[request_id])

    def test_deletes_visit_without_prescription(self):
        patient = make_patient(self.clinic)
        visit = make_visit(patient, self.clinic)
        visit_id = str(visit.id)

        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            action_type='queue_delete',
            payload={'visit_id': visit_id}
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        self.assertTrue(resp.json()['ok'])
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.resolved_by, self.doc_user)
        self.assertFalse(Visit.objects.filter(id=visit_id).exists())

    def test_fails_when_prescription_exists(self):
        from prescription.models import Prescription
        patient = make_patient(self.clinic)
        visit = make_visit(patient, self.clinic)
        # Create a minimal prescription
        Prescription.objects.create(
            visit=visit,
            doctor=self.doc_sm,
            raw_clinical_note='Fever',
        )
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            action_type='queue_delete',
            payload={'visit_id': str(visit.id)}
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['status'], 'failed')
        req.refresh_from_db()
        self.assertEqual(req.status, 'failed')
        self.assertIn('prescription', req.failure_detail.lower())
        # Visit must still exist
        self.assertTrue(Visit.objects.filter(id=visit.id).exists())

    def test_fails_with_nonexistent_visit(self):
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            action_type='queue_delete',
            payload={'visit_id': str(uuid.uuid4())}
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        data = resp.json()
        self.assertEqual(data['status'], 'failed')

    def test_redirect_on_success(self):
        patient = make_patient(self.clinic)
        visit = make_visit(patient, self.clinic)
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            action_type='queue_delete',
            payload={'visit_id': str(visit.id)}
        )
        self.login(self.doc_user)
        self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        req.refresh_from_db()
        self.assertEqual(req.result_data.get('redirect'), '/')


# ══════════════════════════════════════════════════════════════════════════════
# 10. Executor: bill_reversal
# ══════════════════════════════════════════════════════════════════════════════

class TestBillReversalExecutor(SupervisedBase):

    def _resolve_url(self, request_id):
        return reverse('accounts:supervised_resolve', args=[request_id])

    def _setup_bill(self, qty=10):
        patient = make_patient(self.clinic)
        visit = make_visit(patient, self.clinic)
        item = make_pharmacy_item(self.clinic)
        batch = make_batch(item, qty=100)
        bill, di = make_bill(visit, self.clinic, item, batch, qty=qty)
        return visit, item, batch, bill, di

    def test_reversal_restores_stock(self):
        visit, item, batch, bill, di = self._setup_bill(qty=10)
        initial_stock = batch.quantity  # 100

        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='bill_reversal',
            payload={'bill_id': bill.pk}
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        self.assertTrue(resp.json()['ok'])

        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.resolved_by, self.doc_user)

        # Bill and dispensed items deleted
        self.assertFalse(PharmacyBill.objects.filter(pk=bill.pk).exists())
        self.assertFalse(DispensedItem.objects.filter(pk=di.pk).exists())

        # Stock restored
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, initial_stock + 10)

    def test_reversal_redirect_points_to_dispense(self):
        visit, item, batch, bill, di = self._setup_bill()
        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='bill_reversal',
            payload={'bill_id': bill.pk}
        )
        self.login(self.doc_user)
        self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        req.refresh_from_db()
        self.assertIn(str(visit.id), req.result_data.get('redirect', ''))

    def test_reversal_fails_for_wrong_clinic(self):
        other_clinic = make_clinic('Other')
        patient = make_patient(other_clinic)
        # Patient in other_clinic but supervisor is in self.clinic
        # Bill in other_clinic — executor should raise DoesNotExist
        visit = make_visit(patient, other_clinic)
        item = make_pharmacy_item(other_clinic)
        batch = make_batch(item)
        bill, _ = make_bill(visit, other_clinic, item, batch)

        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='bill_reversal',
            payload={'bill_id': bill.pk}
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        data = resp.json()
        self.assertEqual(data['status'], 'failed')
        # Stock should not have changed
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 100)

    def test_reversal_multiple_dispensed_items(self):
        """Bill with 2 different medicines — both stocks restored."""
        patient = make_patient(self.clinic)
        visit = make_visit(patient, self.clinic)
        item1 = make_pharmacy_item(self.clinic, 'Med A')
        item2 = make_pharmacy_item(self.clinic, 'Med B')
        batch1 = make_batch(item1, qty=50)
        batch2 = make_batch(item2, qty=80)
        di1 = DispensedItem.objects.create(
            visit=visit, pharmacy_item=item1, batch=batch1,
            quantity_dispensed=5, unit_price=decimal.Decimal('10.00')
        )
        di2 = DispensedItem.objects.create(
            visit=visit, pharmacy_item=item2, batch=batch2,
            quantity_dispensed=8, unit_price=decimal.Decimal('20.00')
        )
        bill = PharmacyBill.objects.create(
            visit=visit, clinic=self.clinic,
            bill_number='BILL-MULTI-001', final_amount=230
        )

        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='bill_reversal', payload={'bill_id': bill.pk}
        )
        self.login(self.doc_user)
        self.post_json(self._resolve_url(req.id), {'decision': 'approve'})

        batch1.refresh_from_db()
        batch2.refresh_from_db()
        self.assertEqual(batch1.quantity, 55)  # 50 + 5
        self.assertEqual(batch2.quantity, 88)  # 80 + 8


# ══════════════════════════════════════════════════════════════════════════════
# 11. Executor: medicine_return
# ══════════════════════════════════════════════════════════════════════════════

class TestMedicineReturnExecutor(SupervisedBase):

    def _resolve_url(self, request_id):
        return reverse('accounts:supervised_resolve', args=[request_id])

    def _setup(self):
        patient = make_patient(self.clinic)
        visit = make_visit(patient, self.clinic)
        item = make_pharmacy_item(self.clinic)
        batch = make_batch(item, qty=100)
        bill, di = make_bill(visit, self.clinic, item, batch, qty=10)
        return visit, item, batch, bill, di

    def test_partial_return_restores_stock(self):
        visit, item, batch, bill, di = self._setup()

        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='medicine_return',
            payload={
                'bill_id': bill.pk,
                'returns': [{'dispensed_item_id': di.pk, 'return_qty': 3}]
            }
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        self.assertTrue(resp.json()['ok'])

        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.resolved_by, self.doc_user)

        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 103)  # 100 + 3 returned

        di.refresh_from_db()
        self.assertEqual(di.quantity_returned, 3)

    def test_full_return(self):
        visit, item, batch, bill, di = self._setup()
        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='medicine_return',
            payload={
                'bill_id': bill.pk,
                'returns': [{'dispensed_item_id': di.pk, 'return_qty': 10}]
            }
        )
        self.login(self.doc_user)
        self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 110)

    def test_return_more_than_dispensed_fails(self):
        visit, item, batch, bill, di = self._setup()
        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='medicine_return',
            payload={
                'bill_id': bill.pk,
                'returns': [{'dispensed_item_id': di.pk, 'return_qty': 99}]
            }
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        data = resp.json()
        self.assertEqual(data['status'], 'failed')
        # Stock unchanged
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 100)

    def test_return_zero_qty_fails(self):
        visit, item, batch, bill, di = self._setup()
        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='medicine_return',
            payload={
                'bill_id': bill.pk,
                'returns': [{'dispensed_item_id': di.pk, 'return_qty': 0}]
            }
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        data = resp.json()
        self.assertEqual(data['status'], 'failed')
        self.assertIn('zero', data.get('failure_detail', '').lower())

    def test_cumulative_returns_tracked(self):
        """Second return on same item adds to quantity_returned."""
        visit, item, batch, bill, di = self._setup()

        for return_qty in [2, 3]:
            req = make_supervised_request(
                self.clinic, self.ph_user, self.ph_sm,
                action_type='medicine_return',
                payload={
                    'bill_id': bill.pk,
                    'returns': [{'dispensed_item_id': di.pk, 'return_qty': return_qty}]
                }
            )
            self.login(self.doc_user)
            self.post_json(self._resolve_url(req.id), {'decision': 'approve'})

        di.refresh_from_db()
        self.assertEqual(di.quantity_returned, 5)

    def test_wrong_clinic_bill_fails(self):
        other_clinic = make_clinic('Other')
        patient = make_patient(other_clinic)
        visit = make_visit(patient, other_clinic)
        item = make_pharmacy_item(other_clinic)
        batch = make_batch(item)
        bill, di = make_bill(visit, other_clinic, item, batch)

        req = make_supervised_request(
            self.clinic, self.ph_user, self.ph_sm,
            action_type='medicine_return',
            payload={'bill_id': bill.pk, 'returns': [
                {'dispensed_item_id': di.pk, 'return_qty': 1}
            ]}
        )
        self.login(self.doc_user)
        resp = self.post_json(self._resolve_url(req.id), {'decision': 'approve'})
        self.assertEqual(resp.json()['status'], 'failed')


# ══════════════════════════════════════════════════════════════════════════════
# 12. supervised_log_view
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisedLogView(SupervisedBase):

    def _url(self):
        return reverse('accounts:supervised_log')

    def _resolve(self, req, decision='deny'):
        self.login(self.doc_user)
        self.post_json(
            reverse('accounts:supervised_resolve', args=[req.id]),
            {'decision': decision, 'denial_reason': 'Test reason'}
        )

    def test_loads_without_error(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self._resolve(req, 'deny')
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_no_underscore_attribute_error(self):
        """Verifies the _resolver_display → resolver_display fix is working."""
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self._resolve(req, 'deny')
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        # If template has underscore issue, Django raises TemplateSyntaxError
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'TemplateSyntaxError')

    def test_resolver_name_shown(self):
        req = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self._resolve(req, 'deny')
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertContains(resp, 'Dr. Test')

    def test_shows_resolved_requests_only(self):
        pending = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        resolved = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self._resolve(resolved, 'deny')
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        reqs = list(resp.context['requests'])
        ids = [str(r.id) for r in reqs]
        self.assertIn(str(resolved.id), ids)
        self.assertNotIn(str(pending.id), ids)

    def test_filter_by_action_type(self):
        req1 = make_supervised_request(self.clinic, self.rec_user, self.rec_sm,
                                       action_type='queue_delete')
        req2 = make_supervised_request(self.clinic, self.ph_user, self.ph_sm,
                                       action_type='bill_reversal')
        for r in [req1, req2]:
            self._resolve(r, 'deny')
        self.login(self.doc_user)
        resp = self.client.get(self._url() + '?action_type=queue_delete')
        reqs = list(resp.context['requests'])
        ids = [str(r.id) for r in reqs]
        self.assertIn(str(req1.id), ids)
        self.assertNotIn(str(req2.id), ids)

    def test_filter_by_status(self):
        req1 = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        req2 = make_supervised_request(self.clinic, self.rec_user, self.rec_sm)
        self._resolve(req1, 'deny')
        self._resolve(req2, 'deny')
        req2.refresh_from_db()
        # Manually set one to cancelled
        req2.status = 'cancelled'
        req2.save()
        self.login(self.doc_user)
        resp = self.client.get(self._url() + '?status=denied')
        reqs = list(resp.context['requests'])
        ids = [str(r.id) for r in reqs]
        self.assertIn(str(req1.id), ids)
        self.assertNotIn(str(req2.id), ids)

    def test_non_supervisor_gets_403(self):
        self.login(self.rec_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403)

    def test_empty_log_no_crash(self):
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_detail_lines_rendered_in_template(self):
        req = make_supervised_request(
            self.clinic, self.rec_user, self.rec_sm,
            payload={'detail_lines': ['Paracetamol × 5 @ ₹5.00']}
        )
        self._resolve(req, 'deny')
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertContains(resp, 'Paracetamol')


# ══════════════════════════════════════════════════════════════════════════════
# 13. supervised_pending_view (HTML page)
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisedPendingView(SupervisedBase):

    def _url(self):
        return reverse('accounts:supervised_pending')

    def test_doctor_can_access(self):
        self.login(self.doc_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_access(self):
        self.login(self.admin_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_receptionist_gets_403(self):
        self.login(self.rec_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403)

    def test_pharmacist_gets_403(self):
        self.login(self.ph_user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403)


# ══════════════════════════════════════════════════════════════════════════════
# 14. is_supervisor helper
# ══════════════════════════════════════════════════════════════════════════════

class TestIsSupervisorHelper(SupervisedBase):

    def test_doctor_is_supervisor(self):
        from accounts.supervised_views import _is_supervisor
        self.doc_user.staff_profile = self.doc_sm
        self.assertTrue(_is_supervisor(self.doc_user))

    def test_admin_is_supervisor(self):
        from accounts.supervised_views import _is_supervisor
        self.admin_user.staff_profile = self.admin_sm
        self.assertTrue(_is_supervisor(self.admin_user))

    def test_receptionist_is_not_supervisor(self):
        from accounts.supervised_views import _is_supervisor
        self.rec_user.staff_profile = self.rec_sm
        self.assertFalse(_is_supervisor(self.rec_user))

    def test_pharmacist_is_not_supervisor(self):
        from accounts.supervised_views import _is_supervisor
        self.ph_user.staff_profile = self.ph_sm
        self.assertFalse(_is_supervisor(self.ph_user))

    def test_superuser_is_supervisor(self):
        from accounts.supervised_views import _is_supervisor
        su = User.objects.create_superuser('su', password='x')
        self.assertTrue(_is_supervisor(su))


# ══════════════════════════════════════════════════════════════════════════════
# 9. Supervisor bypass — admin/doctor auto-execute without approval queue
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisorBypass(SupervisedBase):
    """
    Doctors and admins should auto-execute supervised actions immediately
    when they raise them — no approval queue, no overlay polling.
    The response must include auto_approved=True and the action outcome.
    """

    def setUp(self):
        super().setUp()
        self.patient = make_patient(self.clinic)
        self.item = make_pharmacy_item(self.clinic)
        self.batch = make_batch(self.item, qty=50)

    def _post_request(self, user, payload):
        self.login(user)
        return self.post_json(reverse('accounts:supervised_request'), payload)

    # ── doctor bypasses for queue_delete ───────────────────────────────────

    def test_doctor_queue_delete_auto_executes(self):
        """Doctor deleting a visit should succeed immediately (auto_approved=True)."""
        visit = make_visit(self.patient, self.clinic)
        resp = self._post_request(self.doc_user, {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': str(visit.id)},
            'description': 'Delete test visit',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data.get('auto_approved'))
        self.assertEqual(data['status'], 'approved')
        self.assertIn('redirect', data)
        # Visit should be deleted from DB
        from reception.models import Visit
        self.assertFalse(Visit.objects.filter(id=visit.id).exists())

    def test_admin_queue_delete_auto_executes(self):
        """Admin deleting a visit should also auto-execute."""
        visit = make_visit(self.patient, self.clinic)
        resp = self._post_request(self.admin_user, {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': str(visit.id)},
            'description': 'Delete test visit',
        })
        data = resp.json()
        self.assertTrue(data.get('auto_approved'))
        self.assertEqual(data['status'], 'approved')
        from reception.models import Visit
        self.assertFalse(Visit.objects.filter(id=visit.id).exists())

    def test_doctor_bill_reversal_auto_executes(self):
        """Doctor reversing a bill should auto-execute."""
        visit = make_visit(self.patient, self.clinic)
        bill, di = make_bill(visit, self.clinic, self.item, self.batch, qty=5)
        resp = self._post_request(self.doc_user, {
            'action_type': 'bill_reversal',
            'action_payload': {'bill_id': bill.pk},
            'description': 'Reverse bill',
        })
        data = resp.json()
        self.assertTrue(data.get('auto_approved'))
        self.assertEqual(data['status'], 'approved')
        # Bill deleted, dispensed units restored to batch (50 + 5 = 55)
        self.assertFalse(PharmacyBill.objects.filter(pk=bill.pk).exists())
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 55)

    def test_doctor_medicine_return_auto_executes(self):
        """Doctor processing a return should auto-execute."""
        visit = make_visit(self.patient, self.clinic)
        bill, di = make_bill(visit, self.clinic, self.item, self.batch, qty=10)
        resp = self._post_request(self.doc_user, {
            'action_type': 'medicine_return',
            'action_payload': {
                'bill_id': bill.pk,
                'returns': [{'dispensed_item_id': di.pk, 'return_qty': 3}],
            },
            'description': 'Return 3 units',
        })
        data = resp.json()
        self.assertTrue(data.get('auto_approved'))
        self.assertEqual(data['status'], 'approved')
        di.refresh_from_db()
        self.assertEqual(di.quantity_returned, 3)

    def test_staff_does_not_bypass(self):
        """Receptionist's request must stay pending and go through the normal flow."""
        visit = make_visit(self.patient, self.clinic)
        resp = self._post_request(self.rec_user, {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': str(visit.id)},
            'description': 'Delete visit',
        })
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertNotIn('auto_approved', data)
        self.assertIn('request_id', data)
        # Visit must still exist
        from reception.models import Visit
        self.assertTrue(Visit.objects.filter(id=visit.id).exists())

    def test_pharmacist_does_not_bypass(self):
        """Pharmacist's bill reversal must go through approval queue."""
        visit = make_visit(self.patient, self.clinic)
        bill, di = make_bill(visit, self.clinic, self.item, self.batch)
        resp = self._post_request(self.ph_user, {
            'action_type': 'bill_reversal',
            'action_payload': {'bill_id': bill.pk},
            'description': 'Reverse bill',
        })
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertNotIn('auto_approved', data)
        # Bill must still exist
        self.assertTrue(PharmacyBill.objects.filter(pk=bill.pk).exists())

    def test_supervisor_bypass_auto_approved_is_logged(self):
        """Auto-approved requests are saved as STATUS_APPROVED in the DB (audit trail)."""
        visit = make_visit(self.patient, self.clinic)
        resp = self._post_request(self.doc_user, {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': str(visit.id)},
            'description': 'Delete visit',
        })
        data = resp.json()
        self.assertTrue(data.get('auto_approved'))
        req = SupervisedActionRequest.objects.get(id=data['request_id'])
        self.assertEqual(req.status, SupervisedActionRequest.STATUS_APPROVED)
        self.assertEqual(req.resolved_by, self.doc_user)
        self.assertIsNotNone(req.resolved_at)

    def test_supervisor_bypass_failure_returns_failed_status(self):
        """If the auto-execute action fails, response has status=failed."""
        # queue_delete with a non-existent visit_id → ValueError in executor
        resp = self._post_request(self.doc_user, {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': str(uuid.uuid4())},
            'description': 'Delete non-existent visit',
        })
        data = resp.json()
        self.assertTrue(data.get('auto_approved'))
        self.assertEqual(data['status'], 'failed')
        self.assertIn('failure_detail', data)

    def test_supervisor_bypass_delete_visit_with_prescription_fails(self):
        """Deleting a visit that has a prescription should return status=failed."""
        from prescription.models import Prescription
        visit = make_visit(self.patient, self.clinic)
        Prescription.objects.create(
            visit=visit,
            doctor=self.doc_sm,
            raw_clinical_note='Fever for 3 days',
            diagnosis='Viral fever',
        )
        resp = self._post_request(self.doc_user, {
            'action_type': 'queue_delete',
            'action_payload': {'visit_id': str(visit.id)},
            'description': 'Delete visit with rx',
        })
        data = resp.json()
        self.assertTrue(data.get('auto_approved'))
        self.assertEqual(data['status'], 'failed')
        # Visit must still exist
        from reception.models import Visit
        self.assertTrue(Visit.objects.filter(id=visit.id).exists())


# ══════════════════════════════════════════════════════════════════════════════
# 10. Inventory Report — MRP visibility gating
# ══════════════════════════════════════════════════════════════════════════════

class TestInventoryReportMRPGating(SupervisedBase):
    """
    Staff (non-analytics) should NOT see MRP column or MRP summary card.
    Supervisors with can_view_analytics=True should see MRP.
    """

    def setUp(self):
        super().setUp()
        # Add can_view_pharmacy to pharmacist so they can access the report
        self.ph_sm.can_view_pharmacy = True
        self.ph_sm.save()

    def _get_report(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('pharmacy:inventory_report'))

    def _make_inventory(self):
        """Add one item+batch so table headers are rendered."""
        item = make_pharmacy_item(self.clinic, 'Amoxicillin 250mg')
        make_batch(item, qty=20)

    def test_analytics_staff_sees_mrp_summary_card(self):
        """Doctor (can_view_analytics=True) sees MRP Value summary card."""
        resp = self._get_report(self.doc_user)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'MRP Value')

    def test_analytics_staff_sees_mrp_column_header(self):
        """Doctor sees MRP (₹) column header when there are inventory items."""
        self._make_inventory()
        resp = self._get_report(self.doc_user)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'MRP (₹)')

    def test_non_analytics_staff_no_mrp_summary_card(self):
        """Pharmacist must not see MRP Value summary card."""
        resp = self._get_report(self.ph_user)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'MRP Value')

    def test_non_analytics_staff_no_mrp_column(self):
        """Pharmacist must NOT see MRP column header even with inventory items."""
        self._make_inventory()
        resp = self._get_report(self.ph_user)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'MRP (₹)')
