"""
Clinic self-registration: every registration is activated immediately (no manual approval).

provision_clinic() turns a ClinicRegistrationRequest into a live Clinic + login User +
admin StaffMember, and marks the request 'approved' — referral payouts for executives
count approved registrations, so that status must be kept.
"""
import logging

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from .models import Clinic, StaffMember
from .permissions import set_permissions_from_role

logger = logging.getLogger(__name__)


class ProvisioningError(Exception):
    pass


def provision_clinic(reg) -> StaffMember:
    """Create the clinic and its admin login from a registration request (atomic)."""
    if User.objects.filter(username=reg.phone).exists():
        raise ProvisioningError(f'A login for mobile {reg.phone} already exists.')

    with transaction.atomic():
        clinic = Clinic.objects.create(
            name=reg.clinic_name,
            city=reg.city,
            state=reg.state,
            phone=reg.clinic_phone,
        )
        names = (reg.doctor_name or '').split()
        user = User(
            username=reg.phone,
            email=reg.email,
            first_name=names[0] if names else '',
            last_name=' '.join(names[1:]),
        )
        user.password = reg.password_hash   # hashed with make_password at registration
        user.save()

        sm = StaffMember.objects.create(
            user=user,
            clinic=clinic,
            role='admin',
            display_name=reg.doctor_name,
            qualification=reg.qualification,
            registration_number=reg.registration_number,
            tour_completed=False,
        )
        set_permissions_from_role(sm)
        sm.save()

        reg.status = 'approved'
        reg.reviewed_at = timezone.now()
        reg.save(update_fields=['status', 'reviewed_at'])

    logger.info('CLINIC_AUTO_ACTIVATED clinic=%s phone=%s', reg.clinic_name, reg.phone)
    return sm
