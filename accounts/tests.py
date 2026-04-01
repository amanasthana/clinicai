"""
Tests for multi-clinic support (Phase 5) and regression for existing features.
"""
import json
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import Clinic, StaffMember
from accounts.permissions import set_permissions_from_role


def make_clinic(name, city='Mumbai'):
    return Clinic.objects.create(name=name, address='1 Test Rd', city=city, phone='9000000099')


def make_user(username, password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def make_membership(user, clinic, role='doctor', display_name='Dr. Test'):
    sm = StaffMember.objects.create(
        user=user, clinic=clinic, role=role, display_name=display_name,
    )
    set_permissions_from_role(sm)
    sm.save()
    return sm


# ---------------------------------------------------------------------------
# Model — multiple memberships per user
# ---------------------------------------------------------------------------

class MultiClinicModelTest(TestCase):

    def test_user_can_have_two_memberships(self):
        user = make_user('multiclinic_doc')
        c1 = make_clinic('Clinic A')
        c2 = make_clinic('Clinic B')
        make_membership(user, c1)
        make_membership(user, c2)
        self.assertEqual(StaffMember.objects.filter(user=user).count(), 2)

    def test_each_membership_has_correct_clinic(self):
        user = make_user('multicheck_doc')
        c1 = make_clinic('Clinic Alpha')
        c2 = make_clinic('Clinic Beta')
        make_membership(user, c1, display_name='Dr. Alpha')
        make_membership(user, c2, display_name='Dr. Beta')
        clinics = set(StaffMember.objects.filter(user=user).values_list('clinic__name', flat=True))
        self.assertIn('Clinic Alpha', clinics)
        self.assertIn('Clinic Beta', clinics)

    def test_two_users_at_same_clinic(self):
        clinic = make_clinic('Shared Clinic')
        u1 = make_user('doc1_shared')
        u2 = make_user('doc2_shared')
        make_membership(u1, clinic, role='doctor')
        make_membership(u2, clinic, role='receptionist')
        self.assertEqual(StaffMember.objects.filter(clinic=clinic).count(), 2)


# ---------------------------------------------------------------------------
# Middleware — staff_profile is set on request.user
# ---------------------------------------------------------------------------

class ActiveClinicMiddlewareTest(TestCase):

    def test_middleware_sets_staff_profile_for_single_clinic_user(self):
        user = make_user('mw_single')
        clinic = make_clinic('MW Clinic')
        make_membership(user, clinic, display_name='Dr. MW')
        client = Client()
        client.login(username='mw_single', password='testpass123')
        resp = client.get('/')
        self.assertEqual(resp.status_code, 200)

    def test_middleware_falls_back_to_first_clinic_without_session(self):
        user = make_user('mw_fallback')
        c1 = make_clinic('MWC First')
        c2 = make_clinic('MWC Second')
        make_membership(user, c1, display_name='Dr. First')
        make_membership(user, c2, display_name='Dr. Second')
        client = Client()
        client.login(username='mw_fallback', password='testpass123')
        resp = client.get('/')
        self.assertEqual(resp.status_code, 200)

    def test_superuser_still_reaches_admin_panel(self):
        User.objects.create_superuser('mw_super', 'super@test.com', 'superpass')
        client = Client()
        client.login(username='mw_super', password='superpass')
        resp = client.get('/accounts/admin-panel/')
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Switch clinic
# ---------------------------------------------------------------------------

class SwitchClinicViewTest(TestCase):

    def setUp(self):
        self.user = make_user('switcher_doc')
        self.c1 = make_clinic('Switch Clinic 1')
        self.c2 = make_clinic('Switch Clinic 2')
        self.m1 = make_membership(self.user, self.c1, display_name='Dr. Switch')
        self.m2 = make_membership(self.user, self.c2, display_name='Dr. Switch')
        self.client = Client()
        self.client.login(username='switcher_doc', password='testpass123')

    def test_switch_sets_session_to_new_membership(self):
        self.client.post('/accounts/switch-clinic/', {'staff_id': self.m2.pk, 'next': '/'})
        self.assertEqual(self.client.session.get('active_staff_id'), self.m2.pk)

    def test_switch_redirects_to_next_param(self):
        resp = self.client.post('/accounts/switch-clinic/', {'staff_id': self.m2.pk, 'next': '/pharmacy/'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/pharmacy/', resp['Location'])

    def test_cannot_switch_to_other_users_membership(self):
        other_user = make_user('other_switcher')
        c3 = make_clinic('Other Switch Clinic')
        other_membership = make_membership(other_user, c3)
        self.client.post('/accounts/switch-clinic/', {'staff_id': other_membership.pk, 'next': '/'})
        self.assertNotEqual(self.client.session.get('active_staff_id'), other_membership.pk)

    def test_switch_requires_login(self):
        anon = Client()
        resp = anon.post('/accounts/switch-clinic/', {'staff_id': self.m2.pk, 'next': '/'})
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Add clinic
# ---------------------------------------------------------------------------

class AddClinicViewTest(TestCase):

    def setUp(self):
        self.user = make_user('addclinic_doc')
        self.clinic = make_clinic('Original Clinic')
        make_membership(self.user, self.clinic, role='doctor', display_name='Dr. Add')
        self.client = Client()
        self.client.login(username='addclinic_doc', password='testpass123')

    def test_add_clinic_page_loads(self):
        resp = self.client.get('/accounts/add-clinic/')
        self.assertEqual(resp.status_code, 200)

    def test_add_clinic_creates_new_clinic(self):
        # add_clinic_view creates a brand-new clinic — no other clinic data exposed
        self.client.post('/accounts/add-clinic/', {
            'clinic_name': 'New Branch Clinic',
            'city': 'Pune',
            'clinic_phone': '9000000088',
            'address': '5 MG Road',
            'display_name': 'Dr. Add',
            'role': 'doctor',
        })
        self.assertTrue(Clinic.objects.filter(name='New Branch Clinic').exists())

    def test_add_clinic_links_membership_to_current_user(self):
        self.client.post('/accounts/add-clinic/', {
            'clinic_name': 'Branch Two',
            'city': 'Nashik',
            'display_name': 'Dr. Add',
            'role': 'doctor',
        })
        new_clinic = Clinic.objects.filter(name='Branch Two').first()
        self.assertIsNotNone(new_clinic)
        self.assertTrue(StaffMember.objects.filter(user=self.user, clinic=new_clinic).exists())

    def test_add_clinic_does_not_expose_other_clinics(self):
        # The GET response must not contain other customers' clinic names
        other_clinic = make_clinic('Secret Other Clinic')
        resp = self.client.get('/accounts/add-clinic/')
        self.assertNotContains(resp, 'Secret Other Clinic')

    def test_add_clinic_requires_login(self):
        anon = Client()
        resp = anon.get('/accounts/add-clinic/')
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Clinic isolation — active clinic scopes all data correctly
# ---------------------------------------------------------------------------

class ClinicIsolationTest(TestCase):

    def setUp(self):
        from reception.models import Patient, Visit

        self.user = make_user('isolation_doc')
        self.c1 = make_clinic('Isolation Clinic 1')
        self.c2 = make_clinic('Isolation Clinic 2')
        self.m1 = make_membership(self.user, self.c1, role='admin', display_name='Dr. Iso')
        self.m2 = make_membership(self.user, self.c2, role='admin', display_name='Dr. Iso')

        self.p1 = Patient.objects.create(
            clinic=self.c1, full_name='Patient One', phone='9100000001', gender='M', age=30,
        )
        Visit.objects.create(
            clinic=self.c1, patient=self.p1, token_number=1,
            visit_date=timezone.now().date(),
        )
        self.p2 = Patient.objects.create(
            clinic=self.c2, full_name='Patient Two', phone='9200000002', gender='F', age=25,
        )
        Visit.objects.create(
            clinic=self.c2, patient=self.p2, token_number=1,
            visit_date=timezone.now().date(),
        )
        self.client = Client()
        self.client.login(username='isolation_doc', password='testpass123')

    def _switch(self, membership):
        self.client.post('/accounts/switch-clinic/', {'staff_id': membership.pk, 'next': '/'})

    def test_clinic1_queue_shows_only_clinic1_patients(self):
        self._switch(self.m1)
        names = [v['name'] for v in self.client.get('/api/queue/').json().get('queue', [])]
        self.assertIn('Patient One', names)
        self.assertNotIn('Patient Two', names)

    def test_clinic2_queue_shows_only_clinic2_patients(self):
        self._switch(self.m2)
        names = [v['name'] for v in self.client.get('/api/queue/').json().get('queue', [])]
        self.assertIn('Patient Two', names)
        self.assertNotIn('Patient One', names)

    def test_pharmacy_search_scoped_to_active_clinic(self):
        from pharmacy.models import PharmacyItem, PharmacyBatch
        item = PharmacyItem.objects.create(clinic=self.c1, custom_name='IsolationDrug')
        PharmacyBatch.objects.create(item=item, quantity=10, unit_price=5)

        self._switch(self.m1)
        r1 = self.client.get('/pharmacy/api/search/?q=IsolationDrug').json()
        self.assertEqual(len(r1['items']), 1)

        self._switch(self.m2)
        r2 = self.client.get('/pharmacy/api/search/?q=IsolationDrug').json()
        self.assertEqual(len(r2['items']), 0)


# ---------------------------------------------------------------------------
# Regression — existing features survive multi-clinic changes
# ---------------------------------------------------------------------------

class RegressionReceptionAfterMultiClinicTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('Regression Reception Clinic')
        self.user = make_user('reg_reception')
        make_membership(self.user, self.clinic, role='admin', display_name='Reg Staff')
        self.client = Client()
        self.client.login(username='reg_reception', password='testpass123')

    def test_reception_dashboard_loads(self):
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_queue_api_works(self):
        resp = self.client.get('/api/queue/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('queue', resp.json())

    def test_patient_search_api_works(self):
        self.assertEqual(self.client.get('/api/patient/search/?phone=9000000001').status_code, 200)

    def test_analytics_view_loads_for_admin(self):
        self.assertEqual(self.client.get('/analytics/').status_code, 200)


class RegressionPrescriptionAfterMultiClinicTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('Regression Rx Clinic')
        self.user = make_user('reg_doctor')
        make_membership(self.user, self.clinic, role='doctor', display_name='Dr. Reg')
        self.client = Client()
        self.client.login(username='reg_doctor', password='testpass123')

    def test_doctor_queue_loads(self):
        self.assertEqual(self.client.get('/rx/doctor/').status_code, 200)

    def test_drug_interaction_api_still_works(self):
        # Seed one interaction so we can assert it fires
        from prescription.models import DrugInteraction
        DrugInteraction.objects.create(
            drug1_keyword='azithromycin', drug2_keyword='warfarin',
            severity='major', effect='Elevated INR / bleeding risk',
        )
        resp = self.client.post(
            '/rx/api/interactions/',
            data=json.dumps({'drugs': ['Tab Warfarin 5mg', 'Tab Azithromycin 500mg']}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('alerts', data)
        self.assertGreater(len(data['alerts']), 0)

    def test_analytics_view_loads_for_doctor(self):
        self.assertEqual(self.client.get('/analytics/').status_code, 200)

# ===========================================================================
# RBAC Tests
# ===========================================================================

from accounts.permissions import ROLE_PERMISSIONS, ALL_PERMISSION_FLAGS, set_permissions_from_role


# ---------------------------------------------------------------------------
# RolePermissionPresetTest
# ---------------------------------------------------------------------------

class RolePermissionPresetTest(TestCase):

    def test_doctor_gets_all_flags_true(self):
        preset = ROLE_PERMISSIONS['doctor']
        for flag in ALL_PERMISSION_FLAGS:
            self.assertTrue(preset[flag], f"doctor should have {flag}=True")

    def test_admin_gets_all_flags_true(self):
        preset = ROLE_PERMISSIONS['admin']
        for flag in ALL_PERMISSION_FLAGS:
            self.assertTrue(preset[flag], f"admin should have {flag}=True")

    def test_receptionist_only_gets_can_register_patients(self):
        preset = ROLE_PERMISSIONS['receptionist']
        self.assertTrue(preset['can_register_patients'])
        self.assertFalse(preset['can_prescribe'])
        self.assertFalse(preset['can_view_pharmacy'])
        self.assertFalse(preset['can_edit_inventory'])
        self.assertFalse(preset['can_dispense_bill'])
        self.assertFalse(preset['can_view_analytics'])
        self.assertFalse(preset['can_manage_staff'])

    def test_pharmacist_gets_correct_flags(self):
        preset = ROLE_PERMISSIONS['pharmacist']
        self.assertFalse(preset['can_register_patients'])
        self.assertFalse(preset['can_prescribe'])
        self.assertTrue(preset['can_view_pharmacy'])
        self.assertTrue(preset['can_edit_inventory'])
        self.assertTrue(preset['can_dispense_bill'])
        self.assertFalse(preset['can_view_analytics'])
        self.assertFalse(preset['can_manage_staff'])

    def test_set_permissions_from_role_applies_correctly(self):
        clinic = make_clinic('Preset Test Clinic')
        user = make_user('preset_test_doc')
        sm = StaffMember.objects.create(
            user=user, clinic=clinic, role='receptionist', display_name='Preset Test'
        )
        # All flags should be False at creation (defaults)
        self.assertFalse(sm.can_prescribe)
        # Now apply preset
        set_permissions_from_role(sm)
        sm.save()
        sm.refresh_from_db()
        self.assertTrue(sm.can_register_patients)
        self.assertFalse(sm.can_prescribe)
        self.assertFalse(sm.can_manage_staff)

    def test_set_permissions_from_role_doctor(self):
        clinic = make_clinic('Preset Doctor Clinic')
        user = make_user('preset_test_doc2')
        sm = StaffMember.objects.create(
            user=user, clinic=clinic, role='doctor', display_name='Preset Doctor'
        )
        set_permissions_from_role(sm)
        sm.save()
        sm.refresh_from_db()
        self.assertTrue(sm.can_prescribe)
        self.assertTrue(sm.can_manage_staff)
        self.assertTrue(sm.can_view_analytics)


# ---------------------------------------------------------------------------
# RequirePermissionDecoratorTest
# ---------------------------------------------------------------------------

class RequirePermissionDecoratorTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('Decorator Test Clinic')

    def test_allowed_user_gets_200(self):
        user = make_user('dec_allowed')
        make_membership(user, self.clinic, role='doctor')
        c = Client()
        c.login(username='dec_allowed', password='testpass123')
        resp = c.get('/rx/doctor/')
        self.assertEqual(resp.status_code, 200)

    def test_disallowed_user_gets_403(self):
        user = make_user('dec_denied')
        make_membership(user, self.clinic, role='receptionist')
        c = Client()
        c.login(username='dec_denied', password='testpass123')
        resp = c.get('/rx/doctor/')
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_gets_302(self):
        c = Client()
        resp = c.get('/rx/doctor/')
        self.assertEqual(resp.status_code, 302)

    def test_superuser_always_gets_200(self):
        User.objects.create_superuser('dec_super', 'sup@test.com', 'superpass')
        c = Client()
        c.login(username='dec_super', password='superpass')
        # superuser has no staff_profile but should pass decorator
        resp = c.get('/accounts/admin-panel/')
        self.assertEqual(resp.status_code, 200)

    def test_403_page_contains_meaningful_content(self):
        user = make_user('dec_403content')
        make_membership(user, self.clinic, role='receptionist')
        c = Client()
        c.login(username='dec_403content', password='testpass123')
        resp = c.get('/rx/doctor/')
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "access", status_code=403)


# ---------------------------------------------------------------------------
# StaffManagementViewTest
# ---------------------------------------------------------------------------

class StaffManagementViewTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('Staff Mgmt Clinic')
        self.admin_user = make_user('mgmt_admin')
        self.admin_sm = make_membership(self.admin_user, self.clinic, role='admin', display_name='Admin User')
        self.client = Client()
        self.client.login(username='mgmt_admin', password='testpass123')

    def test_staff_list_accessible_with_can_manage_staff(self):
        resp = self.client.get('/accounts/staff/')
        self.assertEqual(resp.status_code, 200)

    def test_receptionist_gets_403_on_staff_list(self):
        user = make_user('mgmt_recept')
        make_membership(user, self.clinic, role='receptionist', display_name='Recept User')
        c = Client()
        c.login(username='mgmt_recept', password='testpass123')
        resp = c.get('/accounts/staff/')
        self.assertEqual(resp.status_code, 403)

    def test_add_staff_page_loads_for_admin(self):
        resp = self.client.get('/accounts/staff/add/')
        self.assertEqual(resp.status_code, 200)

    def test_edit_staff_saves_flags_correctly(self):
        target_user = make_user('mgmt_target')
        sm = make_membership(target_user, self.clinic, role='receptionist', display_name='Target Staff')
        resp = self.client.post(f'/accounts/staff/{sm.pk}/edit/', {
            'display_name': 'Target Staff',
            'role': 'receptionist',
            'qualification': '',
            'registration_number': '',
            'can_register_patients': 'on',
            'can_view_analytics': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        sm.refresh_from_db()
        self.assertTrue(sm.can_register_patients)
        self.assertTrue(sm.can_view_analytics)
        self.assertFalse(sm.can_prescribe)

    def test_edit_staff_role_change_applies_preset_on_reset(self):
        target_user = make_user('mgmt_preset_target')
        sm = make_membership(target_user, self.clinic, role='receptionist', display_name='Preset Target')
        resp = self.client.post(f'/accounts/staff/{sm.pk}/edit/', {
            'display_name': 'Preset Target',
            'role': 'pharmacist',
            'qualification': '',
            'registration_number': '',
            'reset_to_role': '1',
        })
        self.assertEqual(resp.status_code, 302)
        sm.refresh_from_db()
        # pharmacist preset
        self.assertTrue(sm.can_view_pharmacy)
        self.assertTrue(sm.can_edit_inventory)
        self.assertFalse(sm.can_prescribe)
        self.assertFalse(sm.can_register_patients)

    def test_delete_staff_also_deletes_user_when_no_other_memberships(self):
        target_user = make_user('mgmt_delete_target')
        sm = make_membership(target_user, self.clinic, role='receptionist', display_name='Delete Target')
        pk = sm.pk
        user_pk = target_user.pk
        resp = self.client.post(f'/accounts/staff/{pk}/delete/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StaffMember.objects.filter(pk=pk).exists())
        # User should also be deleted so the username is freed for reuse
        from django.contrib.auth.models import User as _User
        self.assertFalse(_User.objects.filter(pk=user_pk).exists())

    def test_delete_staff_always_deletes_user(self):
        """Deleting a non-admin staff member always deletes the underlying User account completely,
        even if they had memberships at other clinics (new design: one User = one login identity)."""
        target_user = make_user('mgmt_delete_shared')
        other_clinic = make_clinic('Second Clinic Delete Test')
        make_membership(target_user, other_clinic, role='doctor', display_name='Doc Other')
        sm = make_membership(target_user, self.clinic, role='receptionist', display_name='Delete Shared')
        pk = sm.pk
        user_pk = target_user.pk
        resp = self.client.post(f'/accounts/staff/{pk}/delete/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StaffMember.objects.filter(pk=pk).exists())
        from django.contrib.auth.models import User as _User
        # User is fully deleted so the User ID is freed for re-registration
        self.assertFalse(_User.objects.filter(pk=user_pk).exists())

    def test_cannot_edit_staff_from_another_clinic(self):
        other_clinic = make_clinic('Other Clinic Edit Test')
        other_user = make_user('mgmt_other_clinic_user')
        other_sm = make_membership(other_user, other_clinic, role='doctor', display_name='Other Doc')
        resp = self.client.get(f'/accounts/staff/{other_sm.pk}/edit/')
        self.assertEqual(resp.status_code, 404)

    def test_cannot_delete_yourself(self):
        resp = self.client.post(f'/accounts/staff/{self.admin_sm.pk}/delete/')
        self.assertEqual(resp.status_code, 302)
        # Should still exist
        self.assertTrue(StaffMember.objects.filter(pk=self.admin_sm.pk).exists())


# ---------------------------------------------------------------------------
# RBACReceptionTest
# ---------------------------------------------------------------------------

class RBACReceptionTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('RBAC Reception Clinic')

    def test_receptionist_can_access_reception_dashboard(self):
        user = make_user('rbac_recept_ok')
        make_membership(user, self.clinic, role='receptionist', display_name='Recept OK')
        c = Client()
        c.login(username='rbac_recept_ok', password='testpass123')
        self.assertEqual(c.get('/').status_code, 200)

    def test_receptionist_gets_403_on_doctor_queue(self):
        user = make_user('rbac_recept_rx')
        make_membership(user, self.clinic, role='receptionist', display_name='Recept Rx')
        c = Client()
        c.login(username='rbac_recept_rx', password='testpass123')
        self.assertEqual(c.get('/rx/doctor/').status_code, 403)

    def test_receptionist_gets_403_on_pharmacy(self):
        user = make_user('rbac_recept_ph')
        make_membership(user, self.clinic, role='receptionist', display_name='Recept Ph')
        c = Client()
        c.login(username='rbac_recept_ph', password='testpass123')
        self.assertEqual(c.get('/pharmacy/').status_code, 403)


# ---------------------------------------------------------------------------
# RBACPrescriptionTest
# ---------------------------------------------------------------------------

class RBACPrescriptionTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('RBAC Rx Clinic')

    def test_doctor_can_access_doctor_queue(self):
        user = make_user('rbac_doc_ok')
        make_membership(user, self.clinic, role='doctor', display_name='Doc OK')
        c = Client()
        c.login(username='rbac_doc_ok', password='testpass123')
        self.assertEqual(c.get('/rx/doctor/').status_code, 200)

    def test_receptionist_gets_403_on_doctor_queue(self):
        user = make_user('rbac_recept_dq')
        make_membership(user, self.clinic, role='receptionist', display_name='Recept DQ')
        c = Client()
        c.login(username='rbac_recept_dq', password='testpass123')
        self.assertEqual(c.get('/rx/doctor/').status_code, 403)

    def test_flag_override_receptionist_with_can_prescribe_true_can_access_doctor_queue(self):
        user = make_user('rbac_recept_override')
        sm = make_membership(user, self.clinic, role='receptionist', display_name='Recept Override')
        # Override the flag manually
        sm.can_prescribe = True
        sm.save()
        c = Client()
        c.login(username='rbac_recept_override', password='testpass123')
        self.assertEqual(c.get('/rx/doctor/').status_code, 200)


# ---------------------------------------------------------------------------
# RBACPharmacyTest
# ---------------------------------------------------------------------------

class RBACPharmacyTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('RBAC Pharmacy Clinic')

    def test_pharmacist_can_access_pharmacy_dashboard(self):
        user = make_user('rbac_pharm_ok')
        make_membership(user, self.clinic, role='pharmacist', display_name='Pharm OK')
        c = Client()
        c.login(username='rbac_pharm_ok', password='testpass123')
        self.assertEqual(c.get('/pharmacy/').status_code, 200)

    def test_pharmacist_gets_403_on_reception_dashboard(self):
        user = make_user('rbac_pharm_recept')
        make_membership(user, self.clinic, role='pharmacist', display_name='Pharm Recept')
        c = Client()
        c.login(username='rbac_pharm_recept', password='testpass123')
        self.assertEqual(c.get('/').status_code, 403)

    def test_receptionist_gets_403_on_pharmacy(self):
        user = make_user('rbac_recept_pharm')
        make_membership(user, self.clinic, role='receptionist', display_name='Recept Pharm')
        c = Client()
        c.login(username='rbac_recept_pharm', password='testpass123')
        self.assertEqual(c.get('/pharmacy/').status_code, 403)

    def test_can_edit_inventory_false_blocks_add_stock_for_pharmacist(self):
        user = make_user('rbac_pharm_no_inv')
        sm = make_membership(user, self.clinic, role='pharmacist', display_name='Pharm No Inv')
        # Revoke edit inventory flag
        sm.can_edit_inventory = False
        sm.save()
        c = Client()
        c.login(username='rbac_pharm_no_inv', password='testpass123')
        self.assertEqual(c.get('/pharmacy/add/').status_code, 403)


# ---------------------------------------------------------------------------
# RBACAnalyticsTest
# ---------------------------------------------------------------------------

class RBACAnalyticsTest(TestCase):

    def setUp(self):
        self.clinic = make_clinic('RBAC Analytics Clinic')

    def test_doctor_can_access_analytics(self):
        user = make_user('rbac_analytics_doc')
        make_membership(user, self.clinic, role='doctor', display_name='Analytics Doc')
        c = Client()
        c.login(username='rbac_analytics_doc', password='testpass123')
        self.assertEqual(c.get('/analytics/').status_code, 200)

    def test_receptionist_gets_403_on_analytics(self):
        user = make_user('rbac_analytics_recept')
        make_membership(user, self.clinic, role='receptionist', display_name='Analytics Recept')
        c = Client()
        c.login(username='rbac_analytics_recept', password='testpass123')
        self.assertEqual(c.get('/analytics/').status_code, 403)

    def test_receptionist_with_can_view_analytics_true_can_access_analytics(self):
        user = make_user('rbac_analytics_override')
        sm = make_membership(user, self.clinic, role='receptionist', display_name='Analytics Override')
        sm.can_view_analytics = True
        sm.save()
        c = Client()
        c.login(username='rbac_analytics_override', password='testpass123')
        self.assertEqual(c.get('/analytics/').status_code, 200)


# ---------------------------------------------------------------------------
# Email Nudge and Password Reset Tests
# ---------------------------------------------------------------------------

from accounts.models import PasswordResetRequest


class ForgotPasswordRequestTest(TestCase):
    """Tests for admin-mediated password reset request flow."""

    def setUp(self):
        self.clinic = make_clinic('Reset Request Clinic')
        self.user = make_user('9222000001', password='oldpass123')
        make_membership(self.user, self.clinic, role='doctor', display_name='Reset Doc')

        self.admin_user = make_user('9222000099', password='adminpass123')
        make_membership(self.admin_user, self.clinic, role='admin', display_name='Clinic Admin')

    def test_forgot_password_page_loads(self):
        resp = self.client.get('/accounts/forgot-password/')
        self.assertEqual(resp.status_code, 200)

    def test_forgot_password_shows_security_message(self):
        resp = self.client.get('/accounts/forgot-password/')
        self.assertContains(resp, 'WhatsApp')

    def test_forgot_password_post_with_known_phone_creates_request(self):
        resp = self.client.post('/accounts/forgot-password/', {'phone': '9222000001'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Request received')
        self.assertTrue(PasswordResetRequest.objects.filter(user=self.user, handled=False).exists())

    def test_forgot_password_post_with_unknown_phone_no_error(self):
        """Security: don't reveal whether the account exists."""
        resp = self.client.post('/accounts/forgot-password/', {'phone': '9999999999'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Request received')

    def test_forgot_password_does_not_duplicate_pending_requests(self):
        self.client.post('/accounts/forgot-password/', {'phone': '9222000001'})
        self.client.post('/accounts/forgot-password/', {'phone': '9222000001'})
        self.assertEqual(PasswordResetRequest.objects.filter(user=self.user, handled=False).count(), 1)

    def test_superuser_can_see_pending_reset_in_admin_panel(self):
        PasswordResetRequest.objects.create(user=self.user)
        superuser = User.objects.create_superuser('su_reset_test', 'su@test.com', 'supass')
        self.client.login(username='su_reset_test', password='supass')
        resp = self.client.get('/accounts/admin-panel/')
        self.assertContains(resp, 'Password Reset Requests')

    def test_admin_reset_password_sets_must_change_flag(self):
        sm = self.user.staff_memberships.first()
        self.client.login(username='9222000099', password='adminpass123')
        resp = self.client.post(f'/accounts/staff/{sm.pk}/reset-password/')
        self.assertEqual(resp.status_code, 302)
        sm.refresh_from_db()
        self.assertTrue(sm.must_change_password)

    def test_admin_reset_password_marks_requests_handled(self):
        PasswordResetRequest.objects.create(user=self.user)
        sm = self.user.staff_memberships.first()
        self.client.login(username='9222000099', password='adminpass123')
        self.client.post(f'/accounts/staff/{sm.pk}/reset-password/')
        self.assertFalse(PasswordResetRequest.objects.filter(user=self.user, handled=False).exists())

    def test_login_redirects_to_change_password_when_forced(self):
        sm = self.user.staff_memberships.first()
        sm.must_change_password = True
        sm.save()
        resp = self.client.post('/accounts/login/', {
            'username': '9222000001', 'password': 'oldpass123'
        })
        self.assertRedirects(resp, '/accounts/change-password/')

    def test_change_password_clears_must_change_flag(self):
        sm = self.user.staff_memberships.first()
        sm.must_change_password = True
        sm.save()
        self.client.login(username='9222000001', password='oldpass123')
        self.client.post('/accounts/change-password/', {
            'current_password': 'oldpass123',
            'password1': 'newpass9876',
            'password2': 'newpass9876',
        })
        sm.refresh_from_db()
        self.assertFalse(sm.must_change_password)

    def test_change_password_forced_banner_shown(self):
        sm = self.user.staff_memberships.first()
        sm.must_change_password = True
        sm.save()
        self.client.login(username='9222000001', password='oldpass123')
        resp = self.client.get('/accounts/change-password/')
        self.assertContains(resp, 'Temporary Password')


class ChangePasswordTest(TestCase):
    """Tests for change password (logged-in user)."""

    def setUp(self):
        self.clinic = make_clinic('Change PW Clinic')
        self.user = make_user('9333000001', password='oldpass123')
        make_membership(self.user, self.clinic, role='doctor', display_name='Change PW Doc')

    def test_change_password_requires_login(self):
        resp = self.client.get('/accounts/change-password/')
        self.assertRedirects(resp, '/accounts/login/?next=/accounts/change-password/')

    def test_change_password_wrong_current(self):
        self.client.login(username='9333000001', password='oldpass123')
        resp = self.client.post('/accounts/change-password/', {
            'current_password': 'wrongpass', 'password1': 'newpass9876', 'password2': 'newpass9876',
        })
        self.assertContains(resp, 'incorrect')

    def test_change_password_success(self):
        self.client.login(username='9333000001', password='oldpass123')
        resp = self.client.post('/accounts/change-password/', {
            'current_password': 'oldpass123', 'password1': 'newpass9876', 'password2': 'newpass9876',
        })
        self.assertRedirects(resp, '/')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpass9876'))

    def test_change_password_mismatch(self):
        self.client.login(username='9333000001', password='oldpass123')
        resp = self.client.post('/accounts/change-password/', {
            'current_password': 'oldpass123', 'password1': 'newpass9876', 'password2': 'different',
        })
        self.assertContains(resp, 'do not match')

    def test_change_password_too_short(self):
        self.client.login(username='9333000001', password='oldpass123')
        resp = self.client.post('/accounts/change-password/', {
            'current_password': 'oldpass123', 'password1': 'short', 'password2': 'short',
        })
        self.assertContains(resp, '8 characters')


class AddStaffEmailTest(TestCase):
    """Test that email is collected when adding staff."""

    def setUp(self):
        self.clinic = make_clinic('Staff Email Clinic')
        self.admin = make_user('9444000001', password='testpass123')
        make_membership(self.admin, self.clinic, role='admin', display_name='Admin')

    def test_add_staff_saves_email(self):
        self.client.login(username='9444000001', password='testpass123')
        resp = self.client.post('/accounts/staff/add/', {
            'first_name': 'Jane', 'last_name': 'Doe',
            'phone': '9776543210',
            'username': '9776543210_jane', 'password': 'staffpass123',
            'display_name': 'Jane Doe', 'role': 'receptionist',
            'email': 'jane@clinic.com',
        })
        self.assertRedirects(resp, '/accounts/staff/')
        from django.contrib.auth.models import User
        # Username is the globally-unique ID chosen at creation
        u = User.objects.get(username='9776543210_jane')
        self.assertEqual(u.email, 'jane@clinic.com')

    def test_add_staff_without_email_works(self):
        self.client.login(username='9444000001', password='testpass123')
        resp = self.client.post('/accounts/staff/add/', {
            'first_name': 'John', 'last_name': 'Doe',
            'phone': '9776543211',
            'username': '9776543211_john', 'password': 'staffpass123',
            'display_name': 'John Doe', 'role': 'receptionist',
            'email': '',
        })
        self.assertRedirects(resp, '/accounts/staff/')


class ClinicEditTest(TestCase):
    def setUp(self):
        self.clinic = make_clinic('Test Clinic')
        self.user = make_user('clinic_edit_doc')
        self.sm = make_membership(self.user, self.clinic, role='admin', display_name='Admin Doc')
        self.client = Client()
        self.client.login(username='clinic_edit_doc', password='testpass123')

    def test_get_edit_page(self):
        resp = self.client.get('/accounts/clinic/edit/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test Clinic')

    def test_edit_saves_name(self):
        resp = self.client.post('/accounts/clinic/edit/', {
            'name': 'Updated Clinic', 'address': '2 New Rd', 'city': 'Pune',
            'state': 'Maharashtra', 'phone': '9111111111',
        })
        self.assertEqual(resp.status_code, 302)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.name, 'Updated Clinic')

    def test_edit_rejects_empty_name(self):
        resp = self.client.post('/accounts/clinic/edit/', {
            'name': '', 'address': '', 'city': '', 'state': '', 'phone': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.name, 'Test Clinic')

    def test_non_admin_cannot_edit(self):
        user2 = make_user('recept_edit')
        make_membership(user2, self.clinic, role='receptionist', display_name='Recept')
        c2 = Client()
        c2.login(username='recept_edit', password='testpass123')
        resp = c2.get('/accounts/clinic/edit/')
        self.assertEqual(resp.status_code, 403)


class ClinicDeleteTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser('su_del', 'su@test.com', 'testpass123')
        self.clinic = make_clinic('Delete Me Clinic')
        self.user = make_user('regular_del')
        self.sm = make_membership(self.user, self.clinic, role='admin', display_name='Admin')

    def test_superuser_can_get_confirm_page(self):
        c = Client()
        c.login(username='su_del', password='testpass123')
        resp = c.get(f'/accounts/clinic/{self.clinic.pk}/delete/')
        self.assertEqual(resp.status_code, 200)

    def test_superuser_can_delete(self):
        c = Client()
        c.login(username='su_del', password='testpass123')
        pk = self.clinic.pk
        resp = c.post(f'/accounts/clinic/{pk}/delete/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Clinic.objects.filter(pk=pk).exists())

    def test_regular_user_cannot_delete(self):
        c = Client()
        c.login(username='regular_del', password='testpass123')
        resp = c.post(f'/accounts/clinic/{self.clinic.pk}/delete/')
        self.assertNotEqual(resp.status_code, 200)
        self.assertTrue(Clinic.objects.filter(pk=self.clinic.pk).exists())


# ---------------------------------------------------------------------------
# New staff identity scheme — phone-based globally-unique User ID
# ---------------------------------------------------------------------------

class StaffPhoneUsernameTest(TestCase):
    """
    Tests for the new staff identity model:
    - phone is required and must be 10 digits
    - default username = phone_firstname
    - username is globally unique (not clinic-scoped)
    - min 6 chars on username
    - min 8 chars on password
    - admin role cannot be deleted by staff
    - deletion always removes the User object completely
    """

    def setUp(self):
        self.clinic = make_clinic('Phone Username Clinic')
        self.admin_user = make_user('9100000001', password='adminpass1')
        self.admin_sm = make_membership(self.admin_user, self.clinic, role='admin', display_name='Admin')
        self.client = Client()
        self.client.login(username='9100000001', password='adminpass1')

    # ── Form validation ──────────────────────────────────────────────────────

    def _post_add(self, **overrides):
        data = {
            'first_name': 'Ravi', 'last_name': 'Kumar',
            'phone': '9200000001',
            'username': '9200000001_ravi',
            'password': 'ravi1234!',
            'display_name': 'Ravi Kumar',
            'role': 'receptionist',
            'email': '',
        }
        data.update(overrides)
        return self.client.post('/accounts/staff/add/', data)

    def test_add_staff_success_creates_user_with_phone_username(self):
        resp = self._post_add()
        self.assertRedirects(resp, '/accounts/staff/')
        u = User.objects.get(username='9200000001_ravi')
        sm = StaffMember.objects.get(user=u)
        self.assertEqual(sm.phone, '9200000001')
        self.assertEqual(sm.clinic, self.clinic)

    def test_phone_required(self):
        resp = self._post_add(phone='')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'required')

    def test_phone_must_be_10_digits(self):
        resp = self._post_add(phone='12345')
        self.assertEqual(resp.status_code, 200)
        # form redisplayed with error
        self.assertFalse(User.objects.filter(username='12345_ravi').exists())

    def test_phone_must_be_numeric(self):
        resp = self._post_add(phone='98765abcde')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='98765abcde_ravi').exists())

    def test_username_min_length_6(self):
        # 'ravi' is only 4 chars — should fail
        resp = self._post_add(username='ravi1')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='ravi1').exists())

    def test_username_exactly_6_chars_accepted(self):
        resp = self._post_add(username='ravi12')
        self.assertRedirects(resp, '/accounts/staff/')
        self.assertTrue(User.objects.filter(username='ravi12').exists())

    def test_password_min_length_8(self):
        resp = self._post_add(password='short7!')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='9200000001_ravi').exists())

    def test_username_global_uniqueness_enforced(self):
        """Same User ID cannot be used at two different clinics."""
        # Create user at another clinic with the same username
        other_clinic = make_clinic('Other Clinic Global Unique')
        existing_user = make_user('9200000001_ravi', password='pass1234!')
        make_membership(existing_user, other_clinic, role='doctor', display_name='Ravi')

        resp = self._post_add()  # tries to create same username at this clinic
        self.assertEqual(resp.status_code, 200)  # form error, not redirect
        self.assertContains(resp, 'already taken')
        # Only one User with that name should exist
        self.assertEqual(User.objects.filter(username='9200000001_ravi').count(), 1)

    def test_username_no_double_underscore(self):
        resp = self._post_add(username='9200000001__ravi')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='9200000001__ravi').exists())

    def test_staff_member_phone_stored_on_model(self):
        self._post_add()
        sm = StaffMember.objects.get(user__username='9200000001_ravi')
        self.assertEqual(sm.phone, '9200000001')

    # ── Deletion: admin protection ───────────────────────────────────────────

    def test_cannot_delete_admin_staff(self):
        """Staff with role=admin cannot be deleted via the staff delete view."""
        other_admin_user = make_user('9300000002', password='adminpass2')
        other_admin_sm = make_membership(other_admin_user, self.clinic, role='admin', display_name='Other Admin')
        pk = other_admin_sm.pk
        resp = self.client.post(f'/accounts/staff/{pk}/delete/')
        self.assertEqual(resp.status_code, 302)
        # Must still exist
        self.assertTrue(StaffMember.objects.filter(pk=pk).exists())
        self.assertTrue(User.objects.filter(pk=other_admin_user.pk).exists())

    def test_can_delete_non_admin_staff(self):
        """Receptionist/doctor/pharmacist staff can be deleted by admin."""
        target = make_user('9400000003', password='staffpass3')
        sm = make_membership(target, self.clinic, role='receptionist', display_name='Receptionist')
        pk = sm.pk
        user_pk = target.pk
        resp = self.client.post(f'/accounts/staff/{pk}/delete/')
        self.assertRedirects(resp, '/accounts/staff/')
        self.assertFalse(StaffMember.objects.filter(pk=pk).exists())
        self.assertFalse(User.objects.filter(pk=user_pk).exists())

    def test_delete_doctor_also_deletes_user(self):
        target = make_user('9400000004', password='docpass4')
        sm = make_membership(target, self.clinic, role='doctor', display_name='Dr Test')
        pk = sm.pk
        user_pk = target.pk
        self.client.post(f'/accounts/staff/{pk}/delete/')
        self.assertFalse(User.objects.filter(pk=user_pk).exists())

    def test_delete_pharmacist_also_deletes_user(self):
        target = make_user('9400000005', password='pharmapass5')
        sm = make_membership(target, self.clinic, role='pharmacist', display_name='Pharmacist Test')
        pk = sm.pk
        user_pk = target.pk
        self.client.post(f'/accounts/staff/{pk}/delete/')
        self.assertFalse(User.objects.filter(pk=user_pk).exists())

    # ── login_username property ──────────────────────────────────────────────

    def test_login_username_returns_full_id_for_new_format(self):
        """New-format accounts (phone_name) — login_username returns the full username."""
        user = make_user('9500000001_test', password='pass12345')
        sm = make_membership(user, self.clinic, role='receptionist', display_name='Test')
        self.assertEqual(sm.login_username, '9500000001_test')

    def test_login_username_strips_prefix_for_legacy_format(self):
        """Legacy accounts (clinicphone__staffname) — login_username returns just the staff part."""
        user = make_user('9000000099__legacydoc', password='pass12345')
        sm = make_membership(user, self.clinic, role='doctor', display_name='Legacy Doc')
        self.assertEqual(sm.login_username, 'legacydoc')

    # ── Add staff form — username re-use after deletion ──────────────────────

    def test_deleted_staff_username_can_be_reused(self):
        """After deleting a staff member (User deleted), the same User ID can be registered again."""
        # Create and then delete
        resp1 = self._post_add(phone='9600000006', username='9600000006_reuse')
        self.assertRedirects(resp1, '/accounts/staff/')
        user = User.objects.get(username='9600000006_reuse')
        sm = StaffMember.objects.get(user=user)
        self.client.post(f'/accounts/staff/{sm.pk}/delete/')
        self.assertFalse(User.objects.filter(username='9600000006_reuse').exists())

        # Now re-register with the same User ID — must succeed
        resp2 = self._post_add(phone='9600000006', username='9600000006_reuse',
                               first_name='Reuse', last_name='Test',
                               display_name='Reuse Test')
        self.assertRedirects(resp2, '/accounts/staff/')
        self.assertTrue(User.objects.filter(username='9600000006_reuse').exists())

    # ── Staff list template — admin label shown instead of Remove button ─────

    def test_staff_list_shows_protected_label_for_admin(self):
        # "Admin — protected" only shows for OTHER admins (not the logged-in user's own row)
        second_admin = make_user('9800000099', password='admin2pass')
        make_membership(second_admin, self.clinic, role='admin', display_name='Second Admin')
        resp = self.client.get('/accounts/staff/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Admin \u2014 protected')

    # ── Edit staff page shows User ID ────────────────────────────────────────

    def test_edit_staff_page_shows_login_user_id(self):
        target = make_user('9700000007', password='editpass7')
        sm = make_membership(target, self.clinic, role='receptionist', display_name='Edit Test')
        resp = self.client.get(f'/accounts/staff/{sm.pk}/edit/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '9700000007')  # username shown on page

    # ── Add staff page loads cleanly ─────────────────────────────────────────

    def test_add_staff_page_loads(self):
        resp = self.client.get('/accounts/staff/add/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mobile Number')
        self.assertContains(resp, 'User ID')
