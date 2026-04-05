"""
Management command: seed_demo_doctor
Seeds rich demo data for the production 'doctor' user (Dr. Rakesh Sharma).

DATA ISOLATION GUARANTEE:
  All objects created here (patients, visits, pharmacy items, staff) are linked
  to the doctor's own Clinic via ForeignKey.  No other clinic can ever see
  this data — the FK constraint is the wall.

Usage:
    python manage.py seed_demo_doctor

Safe to run multiple times — uses get_or_create everywhere so it won't
duplicate rows on re-runs.  Existing visits for today are left untouched
(tokens pick up from where they left off).
"""
import datetime
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import Clinic, StaffMember
from reception.models import Patient, Visit, next_token_for_clinic
from pharmacy.models import PharmacyItem, PharmacyBatch, MedicineCatalog


DOCTOR_USERNAME = 'doctor'
DOCTOR_PASSWORD = 'demo12345'  # production password set by user


class Command(BaseCommand):
    help = 'Seed demo patients, inventory and staff for the production doctor account'

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        doctor_user = self._ensure_doctor_user()
        clinic      = self._ensure_clinic(doctor_user)
        doctor_sm   = self._ensure_doctor_staff(doctor_user, clinic)
        self._ensure_extra_staff(clinic)
        patients    = self._ensure_patients(clinic)
        self._ensure_todays_queue(clinic, patients)
        self._ensure_inventory(clinic)

        self.stdout.write(self.style.SUCCESS(
            '\n✅  Demo data seeded for Dr. Rakesh Sharma\n'
            '-------------------------------------------\n'
            f'  Clinic  : {clinic.name}, {clinic.city}\n'
            f'  Login   : username={DOCTOR_USERNAME}  password={DOCTOR_PASSWORD}\n'
            f'  Patients: {clinic.patients.count()} registered\n'
            f'  Queue   : {clinic.visits.filter(visit_date=timezone.now().date()).count()} today\n'
            f'  Stock   : {clinic.pharmacy_items.count()} medicines\n'
            '-------------------------------------------\n'
        ))

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------
    def _ensure_doctor_user(self):
        user, created = User.objects.get_or_create(username=DOCTOR_USERNAME)
        user.set_password(DOCTOR_PASSWORD)
        user.first_name = 'Rakesh'
        user.last_name  = 'Sharma'
        user.save()
        verb = 'Created' if created else 'Updated'
        self.stdout.write(f'  {verb} user: {DOCTOR_USERNAME}')
        return user

    # ------------------------------------------------------------------
    # Clinic
    # ------------------------------------------------------------------
    def _ensure_clinic(self, doctor_user):
        # Find an existing clinic linked to this user
        sm = StaffMember.objects.filter(user=doctor_user).select_related('clinic').first()
        if sm:
            clinic = sm.clinic
            self.stdout.write(f'  Using existing clinic: {clinic.name}')
        else:
            clinic = Clinic.objects.create(
                name='Sharma Clinic & Diagnostics',
                address='14, Laxmi Nagar, Near Hanuman Mandir',
                city='Mumbai',
                state='Maharashtra',
                phone='9876543210',
                default_opd_fee=300,
                default_medicine_discount=5,
            )
            self.stdout.write(f'  Created clinic: {clinic.name}')
        return clinic

    # ------------------------------------------------------------------
    # Doctor staff member
    # ------------------------------------------------------------------
    def _ensure_doctor_staff(self, doctor_user, clinic):
        sm, created = StaffMember.objects.get_or_create(
            user=doctor_user, clinic=clinic,
            defaults=dict(
                role='admin',
                display_name='Dr. Rakesh Sharma',
                qualification='MBBS, MD (General Medicine)',
                registration_number='MH-56789',
                can_register_patients=True,
                can_prescribe=True,
                can_view_pharmacy=True,
                can_edit_inventory=True,
                can_dispense_bill=True,
                can_view_analytics=True,
                can_manage_staff=True,
            )
        )
        if not created:
            sm.display_name  = 'Dr. Rakesh Sharma'
            sm.role          = 'admin'
            sm.qualification = 'MBBS, MD (General Medicine)'
            sm.can_register_patients = True
            sm.can_prescribe         = True
            sm.can_view_pharmacy     = True
            sm.can_edit_inventory    = True
            sm.can_dispense_bill     = True
            sm.can_view_analytics    = True
            sm.can_manage_staff      = True
            sm.save()
        verb = 'Created' if created else 'Updated'
        self.stdout.write(f'  {verb} doctor StaffMember: Dr. Rakesh Sharma')
        return sm

    # ------------------------------------------------------------------
    # Extra staff (receptionist + pharmacist)
    # ------------------------------------------------------------------
    def _ensure_extra_staff(self, clinic):
        extra = [
            dict(
                username='recep_sharma_clinic',
                password='Staff@1234',
                first_name='Meena', last_name='Desai',
                role='receptionist',
                display_name='Meena Desai',
                can_register_patients=True,
            ),
            dict(
                username='pharma_sharma_clinic',
                password='Staff@1234',
                first_name='Suresh', last_name='Naik',
                role='pharmacist',
                display_name='Suresh Naik',
                can_view_pharmacy=True,
                can_dispense_bill=True,
                can_edit_inventory=True,
            ),
        ]
        for s in extra:
            user, _ = User.objects.get_or_create(username=s['username'])
            user.set_password(s.pop('password'))
            user.first_name = s.pop('first_name')
            user.last_name  = s.pop('last_name')
            user.save()
            s.pop('username')
            StaffMember.objects.get_or_create(
                user=user, clinic=clinic,
                defaults=s,
            )
        self.stdout.write('  Extra staff ensured (receptionist + pharmacist)')

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def _ensure_patients(self, clinic):
        patients_data = [
            dict(full_name='Ramesh Kumar',      phone='9811111101', age=52, gender='M',
                 blood_group='B+',  allergies='Penicillin',
                 notes='Hypertensive, on amlodipine'),
            dict(full_name='Sunita Devi',        phone='9811111102', age=34, gender='F',
                 blood_group='O+'),
            dict(full_name='Arjun Mehta',        phone='9811111103', age=28, gender='M',
                 blood_group='A+'),
            dict(full_name='Kavita Joshi',       phone='9811111104', age=45, gender='F',
                 blood_group='A+',  notes='T2DM, HbA1c 7.2, regular follow-up'),
            dict(full_name='Mohan Lal Gupta',    phone='9811111105', age=67, gender='M',
                 blood_group='AB+', allergies='Sulfa drugs'),
            dict(full_name='Priya Nair',         phone='9811111106', age=29, gender='F'),
            dict(full_name='Sunil Pawar',        phone='9811111107', age=41, gender='M',
                 blood_group='B-',  notes='Asthmatic, carries inhaler'),
            dict(full_name='Rekha Sharma',       phone='9811111108', age=55, gender='F',
                 blood_group='O+',  allergies='NSAIDs'),
            dict(full_name='Dinesh Yadav',       phone='9811111109', age=38, gender='M'),
            dict(full_name='Anjali Singh',       phone='9811111110', age=22, gender='F',
                 blood_group='A-'),
            dict(full_name='Harish Tiwari',      phone='9811111111', age=60, gender='M',
                 blood_group='B+',  notes='CKD stage 2, nephrologist referred'),
            dict(full_name='Geeta Mishra',       phone='9811111112', age=48, gender='F'),
            dict(full_name='Ravi Shankar Patel', phone='9811111113', age=35, gender='M',
                 blood_group='O+'),
            dict(full_name='Lakshmi Bai',        phone='9811111114', age=70, gender='F',
                 blood_group='AB+', notes='Osteoporosis, on calcium supplements'),
            dict(full_name='Aakash Verma',       phone='9811111115', age=19, gender='M'),
        ]
        patients = []
        for pd in patients_data:
            p, _ = Patient.objects.get_or_create(
                clinic=clinic, phone=pd['phone'],
                defaults=pd,
            )
            patients.append(p)
        self.stdout.write(f'  Patients ensured: {len(patients)}')
        return patients

    # ------------------------------------------------------------------
    # Today's queue
    # ------------------------------------------------------------------
    def _ensure_todays_queue(self, clinic, patients):
        today = timezone.now().date()
        # Don't re-add if already queued today
        already = set(
            Visit.objects.filter(clinic=clinic, visit_date=today)
                         .values_list('patient_id', flat=True)
        )
        queue_spec = [
            (patients[0],  'Hypertension follow-up, BP check',          'done',            '130/85', '72 kg'),
            (patients[1],  'Fever 101°F, throat pain, 2 days',          'done',            '98/64',  '58 kg'),
            (patients[2],  'Acute lower back pain after lifting',        'in_consultation', '120/78', '80 kg'),
            (patients[3],  'Diabetes follow-up, sugar reports',          'in_consultation', '118/76', '68 kg'),
            (patients[4],  'Chest congestion, mild breathlessness',      'waiting',         '',       ''),
            (patients[5],  'Irregular periods, pelvic pain',             'waiting',         '',       ''),
            (patients[6],  'Asthma exacerbation, wheezing since morning','waiting',         '',       ''),
            (patients[7],  'Joint pain both knees, OA',                  'waiting',         '',       ''),
            (patients[8],  'Pre-employment fitness certificate',         'waiting',         '',       ''),
        ]
        added = 0
        for (patient, complaint, status, bp, weight) in queue_spec:
            if patient.id in already:
                continue
            token = next_token_for_clinic(clinic.id)
            visit = Visit.objects.create(
                patient=patient,
                clinic=clinic,
                token_number=token,
                chief_complaint=complaint,
                status=status,
                vitals_bp=bp,
                vitals_weight=weight,
            )
            now = timezone.now()
            if status == 'done':
                visit.called_at    = now - datetime.timedelta(minutes=30)
                visit.completed_at = now - datetime.timedelta(minutes=10)
                visit.save()
            elif status == 'in_consultation':
                visit.called_at = now - datetime.timedelta(minutes=5)
                visit.save()
            added += 1
        self.stdout.write(f'  Today\'s queue: {added} new visit(s) added')

    # ------------------------------------------------------------------
    # Pharmacy inventory
    # ------------------------------------------------------------------
    def _ensure_inventory(self, clinic):
        today = timezone.now().date()

        inventory = [
            # (custom_name, generic_name, reorder_level, batches)
            # batches = list of (batch_no, qty, unit_price, purchase_price, expiry_months_from_now)
            ('Tab Amlodipine 5mg',    'Amlodipine 5mg',      20,
             [('AM-001', 120, 8.50,  5.00, 18), ('AM-002', 80, 8.50,  5.00, 24)]),

            ('Tab Metformin 500mg',   'Metformin 500mg',     30,
             [('MF-001', 200, 5.00,  3.00, 12), ('MF-002', 150, 5.00,  3.00, 18)]),

            ('Tab Metformin 1000mg',  'Metformin 1000mg',    15,
             [('MF1G-01', 90, 9.00,  5.50, 15)]),

            ('Cap Amoxicillin 500mg', 'Amoxicillin 500mg',   25,
             [('AX-001', 180, 12.00, 7.00, 10)]),

            ('Tab Pantoprazole 40mg', 'Pantoprazole 40mg',   20,
             [('PP-001', 100, 11.00, 6.50, 14)]),

            ('Tab Paracetamol 500mg', 'Paracetamol 500mg',   50,
             [('PC-001', 300, 2.50,  1.50, 24), ('PC-002', 200, 2.50,  1.50, 30)]),

            ('Tab Cetirizine 10mg',   'Cetirizine 10mg',     15,
             [('CT-001', 80, 3.00,   1.80, 20)]),

            ('Syr Amoxicillin 125mg/5ml', 'Amoxicillin susp 125mg/5ml', 10,
             [('SY-001', 30, 55.00, 32.00, 8)]),

            ('Tab Atorvastatin 10mg', 'Atorvastatin 10mg',   15,
             [('AT-001', 120, 15.00, 9.00, 22)]),

            ('Tab Losartan 50mg',     'Losartan 50mg',       15,
             [('LO-001', 90, 14.00,  8.50, 18)]),

            ('Tab Glimepiride 2mg',   'Glimepiride 2mg',     10,
             [('GL-001', 60, 18.00, 11.00, 14)]),

            ('Tab Azithromycin 500mg','Azithromycin 500mg',  10,
             [('AZ-001', 50, 28.00, 17.00, 12)]),

            ('Tab Ibuprofen 400mg',   'Ibuprofen 400mg',     20,
             [('IB-001', 150, 4.50,  2.80, 18)]),

            ('Tab Omeprazole 20mg',   'Omeprazole 20mg',     20,
             [('OM-001', 110, 7.50,  4.50, 16)]),

            ('Inj Diclofenac 75mg/3ml','Diclofenac sodium 75mg/3ml', 5,
             [('DJ-001', 20, 35.00, 22.00, 10)]),

            ('Tab Vitamin D3 60000 IU','Cholecalciferol 60000 IU', 10,
             [('VD-001', 40, 45.00, 28.00, 24)]),

            ('Tab Calcium + D3',      'Calcium carbonate 500mg + Vit D3 250IU', 10,
             [('CA-001', 80, 12.00,  7.00, 20)]),

            ('Syr Paracetamol 250mg/5ml','Paracetamol 250mg/5ml', 8,
             [('SPC-01', 25, 38.00, 22.00, 12)]),

            # Near-expiry batch (2 months out) — shows expiry warning in UI
            ('Tab Doxycycline 100mg', 'Doxycycline 100mg',   10,
             [('DX-OLD', 15, 16.00, 10.00, 2)]),

            # Low-stock item (qty 8, reorder_level 10)
            ('Tab Methotrexate 2.5mg','Methotrexate 2.5mg',  10,
             [('MTX-01', 8, 95.00, 60.00, 18)]),
        ]

        added = 0
        for (cname, cgeneric, reorder, batches) in inventory:
            item, item_created = PharmacyItem.objects.get_or_create(
                clinic=clinic,
                custom_name=cname,
                defaults=dict(
                    custom_generic_name=cgeneric,
                    reorder_level=reorder,
                ),
            )
            if item_created:
                for (bno, qty, uprice, pprice, exp_months) in batches:
                    expiry = today + datetime.timedelta(days=exp_months * 30)
                    PharmacyBatch.objects.create(
                        item=item,
                        batch_number=bno,
                        quantity=qty,
                        unit_price=uprice,
                        purchase_price=pprice,
                        expiry_date=expiry,
                    )
                added += 1

        self.stdout.write(f'  Pharmacy items added: {added} new (existing items untouched)')
