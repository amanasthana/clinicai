import logging

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.utils import timezone

logger = logging.getLogger('accounts')

# Track previous status to detect transitions
_prev_status = {}


@receiver(pre_save, sender='accounts.ClinicRegistrationRequest')
def _capture_prev_status(sender, instance, **kwargs):
    """Remember the pre-save status so we can detect transitions in post_save."""
    if instance.pk:
        try:
            _prev_status[instance.pk] = sender.objects.get(pk=instance.pk).status
        except sender.DoesNotExist:
            pass


@receiver(post_save, sender='accounts.ClinicRegistrationRequest')
def create_clinic_account_on_approval(sender, instance, created, **kwargs):
    """
    Automatically create Clinic + User + StaffMember whenever a registration
    is saved with status='approved' — works whether approval happens via the
    ClinicAI admin panel button OR directly via Django /admin/.
    """
    if instance.status != 'approved':
        return

    # Only act on a status transition (pending → approved), not on re-saves
    prev = _prev_status.pop(instance.pk, None)
    if prev == 'approved':
        return  # Already processed

    # Skip if a User already exists for this phone (already created)
    if User.objects.filter(username=instance.phone).exists():
        logger.info('SIGNAL_APPROVAL_SKIP phone=%s user_already_exists', instance.phone)
        return

    logger.info('SIGNAL_APPROVAL_START pk=%s phone=%s', instance.pk, instance.phone)

    try:
        from django.db import transaction
        from .models import Clinic, StaffMember

        with transaction.atomic():
            # Create Clinic (or reuse if somehow it already exists)
            clinic = Clinic.objects.filter(name=instance.clinic_name, city=instance.city).first()
            if not clinic:
                clinic = Clinic.objects.create(
                    name=instance.clinic_name,
                    city=instance.city,
                    state=instance.state,
                    phone=instance.clinic_phone,
                )

            # Create User (username = phone number)
            user = User(
                username=instance.phone,
                email=instance.email,
                first_name=instance.doctor_name.split()[0] if instance.doctor_name else '',
                last_name=' '.join(instance.doctor_name.split()[1:]) if instance.doctor_name else '',
            )
            user.password = instance.password_hash  # Already hashed by make_password
            user.save()

            # Create StaffMember
            StaffMember.objects.create(
                user=user,
                clinic=clinic,
                role='admin',
                display_name=instance.doctor_name,
                qualification=instance.qualification,
                registration_number=instance.registration_number,
            )

            # Stamp reviewed_at if not set (e.g. when approved via Django admin)
            if not instance.reviewed_at:
                sender.objects.filter(pk=instance.pk).update(reviewed_at=timezone.now())

        logger.info('SIGNAL_APPROVAL_OK clinic=%s phone=%s', instance.clinic_name, instance.phone)

    except Exception as e:
        logger.error('SIGNAL_APPROVAL_FAILED pk=%s error=%s', instance.pk, e, exc_info=True)
