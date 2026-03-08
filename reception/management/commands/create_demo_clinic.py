"""
Management command: create_demo_clinic
Seeds a demo clinic with sample data for testing.

Usage:
    python manage.py create_demo_clinic

Creates:
    - Demo clinic: "City Health Clinic, Mumbai"
    - Admin/Doctor: username=doctor, password=demo1234
    - Receptionist: username=reception, password=demo1234
    - 5 sample patients
    - Today's queue with 4 visits (various statuses)
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from accounts.models import Clinic, StaffMember
from reception.models import Patient, Visit, next_token_for_clinic


class Command(BaseCommand):
    help = 'Seed a demo clinic with sample patients and a queue for testing'

    def handle(self, *args, **options):
        self.stdout.write('Creating demo clinic...')

        # Clean up existing demo data
        Clinic.objects.filter(name='City Health Clinic').delete()
        User.objects.filter(username__in=['doctor', 'reception']).delete()

        # Create clinic
        clinic = Clinic.objects.create(
            name='City Health Clinic',
            address='12, Gandhi Nagar, Near Bus Stand',
            city='Mumbai',
            state='Maharashtra',
            phone='9876543210',
        )

        # Create doctor
        doctor_user = User.objects.create_user(
            username='doctor',
            password='demo1234',
            first_name='Rajesh',
            last_name='Sharma',
        )
        doctor = StaffMember.objects.create(
            user=doctor_user,
            clinic=clinic,
            role='admin',
            display_name='Dr. Rajesh Sharma',
            qualification='MBBS, MD (General Medicine)',
            registration_number='MH-12345',
        )

        # Create receptionist
        recep_user = User.objects.create_user(
            username='reception',
            password='demo1234',
            first_name='Priya',
            last_name='Patil',
        )
        StaffMember.objects.create(
            user=recep_user,
            clinic=clinic,
            role='receptionist',
            display_name='Priya Patil',
        )

        # Sample patients
        patients_data = [
            {'full_name': 'Ramesh Kumar', 'phone': '9812345670', 'age': 52, 'gender': 'M',
             'blood_group': 'B+', 'allergies': 'Penicillin'},
            {'full_name': 'Sunita Devi', 'phone': '9823456781', 'age': 34, 'gender': 'F',
             'blood_group': 'O+'},
            {'full_name': 'Arjun Singh', 'phone': '9834567892', 'age': 28, 'gender': 'M'},
            {'full_name': 'Kavita Joshi', 'phone': '9845678903', 'age': 45, 'gender': 'F',
             'blood_group': 'A+', 'notes': 'Diabetic, regular patient'},
            {'full_name': 'Mohan Lal', 'phone': '9856789014', 'age': 67, 'gender': 'M',
             'blood_group': 'AB+', 'allergies': 'Sulfa drugs'},
        ]
        patients = []
        for pd in patients_data:
            p = Patient.objects.create(clinic=clinic, **pd)
            patients.append(p)

        # Today's visits
        today = timezone.now().date()
        visit_data = [
            (patients[0], 'Chest pain and shortness of breath', 'done'),
            (patients[1], 'Fever and cold for 3 days', 'in_consultation'),
            (patients[2], 'Back pain', 'waiting'),
            (patients[3], 'Diabetes follow-up, sugar check', 'waiting'),
        ]
        for i, (patient, complaint, status) in enumerate(visit_data, start=1):
            visit = Visit.objects.create(
                patient=patient,
                clinic=clinic,
                token_number=i,
                chief_complaint=complaint,
                status=status,
                vitals_bp='120/80' if i % 2 == 0 else '',
            )
            if status == 'done':
                visit.completed_at = timezone.now()
                visit.save()
            elif status == 'in_consultation':
                visit.called_at = timezone.now()
                visit.save()

        self.stdout.write(self.style.SUCCESS(
            '\nDemo clinic created successfully!\n'
            '-----------------------------------\n'
            'Clinic:      City Health Clinic, Mumbai\n'
            'Doctor:      username=doctor     password=demo1234\n'
            'Receptionist: username=reception  password=demo1234\n'
            f'Patients:    {len(patients)} registered\n'
            f'Queue today: {len(visit_data)} visits\n'
            '-----------------------------------\n'
            'Run: python manage.py runserver\n'
            'Open: http://127.0.0.1:8000\n'
        ))
