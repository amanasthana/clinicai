"""
Activate clinic registrations left 'pending' from the old manual-approval process.
Idempotent — safe to run on every deploy; does nothing when nothing is pending.
"""
from django.core.management.base import BaseCommand

from accounts.models import ClinicRegistrationRequest
from accounts.registration import provision_clinic, ProvisioningError


class Command(BaseCommand):
    help = 'Activate legacy pending clinic registrations (registrations are now auto-approved).'

    def handle(self, *args, **options):
        pending = ClinicRegistrationRequest.objects.filter(status='pending').order_by('created_at')
        activated = skipped = 0
        for reg in pending:
            try:
                provision_clinic(reg)
                activated += 1
                self.stdout.write(f'  Activated: {reg.clinic_name} ({reg.phone})')
            except ProvisioningError as e:
                skipped += 1
                self.stdout.write(f'  Skipped {reg.clinic_name} ({reg.phone}): {e}')
        self.stdout.write(f'Pending registrations — activated: {activated}, skipped: {skipped}')
