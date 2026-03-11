"""
Diagnostic command: test the full registration→approval→login flow for a given phone number.
Usage: python manage.py check_clinic_login <phone>
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import ClinicRegistrationRequest, StaffMember


class Command(BaseCommand):
    help = 'Diagnose login issues for a self-registered clinic'

    def add_arguments(self, parser):
        parser.add_argument('phone', type=str, help='10-digit phone number used at registration')

    def handle(self, *args, **options):
        phone = options['phone'].strip()
        self.stdout.write(f'\n=== Checking login for phone: {phone} ===\n')

        # 1. Check ClinicRegistrationRequest
        reqs = ClinicRegistrationRequest.objects.filter(phone=phone)
        if not reqs.exists():
            self.stdout.write(self.style.ERROR(f'[FAIL] No registration request found with phone={phone}'))
        else:
            for r in reqs:
                self.stdout.write(f'[OK] Registration request: pk={r.pk} status={r.status} clinic={r.clinic_name}')
                self.stdout.write(f'     password_hash stored: {r.password_hash[:40]}...')

        # 2. Check User
        try:
            user = User.objects.get(username=phone)
            self.stdout.write(self.style.SUCCESS(f'[OK] User exists: pk={user.pk} username={user.username} is_active={user.is_active}'))
            self.stdout.write(f'     password in DB: {user.password[:40]}...')
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'[FAIL] No User found with username={phone}'))
            self.stdout.write('       → Approval may have failed. Try approving again from admin panel.')
            self.stdout.write('       → Or run: python manage.py migrate (if migration 0005 is not applied)')
            return

        # 3. Check StaffMember
        if hasattr(user, 'staff_profile'):
            sm = user.staff_profile
            self.stdout.write(self.style.SUCCESS(f'[OK] StaffMember: role={sm.role} clinic={sm.clinic.name}'))
        else:
            self.stdout.write(self.style.ERROR('[FAIL] User has NO staff_profile → login will show "not linked to any clinic"'))
            return

        # 4. Check password
        if reqs.exists():
            reg = reqs.order_by('-created_at').first()
            if user.password == reg.password_hash:
                self.stdout.write(self.style.SUCCESS('[OK] Password hash in User matches hash in RegistrationRequest'))
            else:
                self.stdout.write(self.style.WARNING('[WARN] Password hash differs (may have been reset)'))

        # 5. Test backend authenticate
        from accounts.backends import EmailOrUsernameBackend
        backend = EmailOrUsernameBackend()
        result = backend.authenticate(None, username=phone, password='__PLACEHOLDER__')
        if result is None:
            self.stdout.write('[INFO] Backend returned None for placeholder password (expected — password check failed)')
            self.stdout.write('       If backend also returns None for the REAL password, check_password logic is broken.')
        else:
            self.stdout.write(self.style.WARNING('[WARN] Backend authenticated with placeholder password — something is wrong'))

        self.stdout.write('\n=== Summary ===')
        self.stdout.write(f'To log in: go to /accounts/login/')
        self.stdout.write(f'  Username: {phone}')
        self.stdout.write(f'  Password: the one set during registration')
        self.stdout.write(f'  (If still failing, check migration status: python manage.py showmigrations accounts)\n')
