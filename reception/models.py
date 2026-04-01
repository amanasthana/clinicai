import uuid
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


def next_token_for_clinic(clinic_id):
    """Get the next sequential token number for today at this clinic."""
    today = timezone.now().date()
    last = Visit.objects.filter(
        clinic_id=clinic_id, visit_date=today
    ).order_by('-token_number').first()
    return (last.token_number + 1) if last else 1


class Patient(models.Model):
    """
    Master patient record per clinic.
    Primary lookup key is phone number (unique per clinic).
    UUID primary key — never expose sequential IDs in URLs.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(
        'accounts.Clinic', on_delete=models.CASCADE, related_name='patients'
    )
    full_name = models.CharField(max_length=200)
    guardian_name = models.CharField(max_length=150, blank=True, help_text="Husband's / Father's name (optional)")
    phone = models.CharField(max_length=15, db_index=True)  # primary lookup key
    age = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(99)])
    gender = models.CharField(
        max_length=1,
        choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')],
        blank=True,
    )
    address = models.TextField(blank=True)
    blood_group = models.CharField(max_length=5, blank=True)
    allergies = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['clinic', 'phone']
        indexes = [models.Index(fields=['clinic', 'phone'])]

    def __str__(self):
        return f"{self.full_name} ({self.phone})"

    @property
    def gender_display(self):
        return {'M': 'Male', 'F': 'Female', 'O': 'Other'}.get(self.gender, '')


class Visit(models.Model):
    """
    One row per clinic visit. Linked to patient + clinic.
    Token number resets daily per clinic.
    """
    STATUS_CHOICES = [
        ('waiting', 'Waiting'),
        ('in_consultation', 'In Consultation'),
        ('done', 'Done'),
        ('no_show', 'No Show'),
        ('cancelled', 'Cancelled'),
    ]

    CANCELLATION_REASON_CHOICES = [
        ('patient_called', 'Patient called to cancel'),
        ('rescheduled', 'Rescheduled'),
        ('doctor_unavailable', 'Doctor unavailable'),
        ('patient_unwell', 'Patient unwell / hospitalised'),
        ('other', 'Other'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='visits')
    clinic = models.ForeignKey(
        'accounts.Clinic', on_delete=models.CASCADE, related_name='visits'
    )
    token_number = models.PositiveIntegerField()
    chief_complaint = models.CharField(max_length=300, blank=True)
    vitals_bp = models.CharField(max_length=20, blank=True)     # "120/80"
    vitals_temp = models.CharField(max_length=10, blank=True)   # "98.6"
    vitals_weight = models.CharField(max_length=10, blank=True) # "72 kg"
    vitals_spo2 = models.CharField(max_length=10, blank=True)   # "98%"
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    cancellation_reason = models.CharField(max_length=30, blank=True, choices=CANCELLATION_REASON_CHOICES)
    visit_date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    called_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # OPD consultation fee
    PAYMENT_MODE_CHOICES = [
        ('cash',      'Cash'),
        ('upi',       'UPI'),
        ('card',      'Card'),
        ('insurance', 'Insurance'),
        ('waived',    'Waived'),
    ]
    consultation_fee   = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    fee_receipt_number = models.CharField(max_length=30, blank=True)
    fee_paid_at        = models.DateTimeField(null=True, blank=True)
    payment_mode       = models.CharField(max_length=12, choices=PAYMENT_MODE_CHOICES, blank=True)

    @staticmethod
    def generate_receipt_number():
        from django.utils import timezone
        today = timezone.localtime().strftime('%Y%m%d')
        prefix = f'OPD-{today}-'
        existing = Visit.objects.filter(
            fee_receipt_number__startswith=prefix
        ).values_list('fee_receipt_number', flat=True)
        seq = (max(int(n[len(prefix):]) for n in existing) + 1) if existing else 1
        return f'{prefix}{seq:04d}'

    class Meta:
        ordering = ['token_number']
        indexes = [
            models.Index(fields=['clinic', 'visit_date', 'status']),
            models.Index(fields=['patient', '-visit_date']),
        ]

    def __str__(self):
        return f"Token {self.token_number} — {self.patient.full_name} ({self.visit_date})"

    @property
    def status_color(self):
        """Returns Tailwind CSS color class for this status."""
        return {
            'waiting': 'gray',
            'in_consultation': 'blue',
            'done': 'green',
            'no_show': 'red',
            'cancelled': 'red',
        }.get(self.status, 'gray')
