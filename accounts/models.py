from django.db import models
from django.conf import settings


class Clinic(models.Model):
    """Represents one physical clinic location."""
    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, default='Maharashtra')
    phone = models.CharField(max_length=15, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Custom letterhead for printing on pre-printed prescription pads
    letterhead_image = models.ImageField(upload_to='letterheads/', null=True, blank=True)
    letterhead_height_mm = models.PositiveSmallIntegerField(
        default=0,
        help_text='Height of the printed letterhead area in mm. Prescription content starts below this.'
    )
    use_letterhead = models.BooleanField(
        default=False,
        help_text='If True, hide digital header and start content below letterhead_height_mm.'
    )

    def __str__(self):
        return self.name


class StaffMember(models.Model):
    """Links a Django User to a Clinic with a role (doctor, receptionist, etc.)."""
    ROLE_CHOICES = [
        ('doctor', 'Doctor'),
        ('receptionist', 'Receptionist'),
        ('pharmacist', 'Pharmacist'),
        ('admin', 'Clinic Admin'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_memberships',
    )
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='staff')
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    display_name = models.CharField(max_length=120)       # "Dr. Rajesh Sharma"
    qualification = models.CharField(max_length=200, blank=True)   # "MBBS, MD"
    registration_number = models.CharField(max_length=50, blank=True)  # Medical council reg
    created_at = models.DateTimeField(auto_now_add=True)
    show_rx_remarks = models.BooleanField(default=True)

    # Permission flags — set automatically from role preset, can be overridden per staff member
    can_register_patients = models.BooleanField(default=False)
    can_prescribe         = models.BooleanField(default=False)
    can_view_pharmacy     = models.BooleanField(default=False)
    can_edit_inventory    = models.BooleanField(default=False)
    can_dispense_bill     = models.BooleanField(default=False)
    can_view_analytics    = models.BooleanField(default=False)
    can_manage_staff      = models.BooleanField(default=False)
    updated_at            = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()}) — {self.clinic.name}"

    @property
    def is_doctor(self):
        return self.role == 'doctor'


class ClinicRegistrationRequest(models.Model):
    CLINIC_TYPES = [
        ('general', 'General Practice / GP'),
        ('specialist', 'Specialist Clinic'),
        ('multispecialty', 'Multi-specialty'),
        ('dental', 'Dental'),
        ('pediatric', 'Pediatric'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    # Clinic info
    clinic_name = models.CharField(max_length=200)
    clinic_type = models.CharField(max_length=20, choices=CLINIC_TYPES, default='general')
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, default='Maharashtra')
    clinic_phone = models.CharField(max_length=15)

    # Doctor/admin info
    doctor_name = models.CharField(max_length=200)
    qualification = models.CharField(max_length=200, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)

    # Contact & login credentials
    phone = models.CharField(max_length=10)   # becomes Django username
    email = models.EmailField(blank=True)
    password_hash = models.CharField(max_length=300)  # Django make_password output

    # Review
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.clinic_name} ({self.get_status_display()})"


class ContactMessage(models.Model):
    INQUIRY_TYPES = [
        ('new_clinic', 'Interested in joining ClinicAI'),
        ('existing', 'I am an existing clinic'),
        ('pricing', 'Pricing question'),
        ('support', 'Technical support'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=15, blank=True)
    inquiry_type = models.CharField(max_length=20, choices=INQUIRY_TYPES, default='new_clinic')
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} — {self.get_inquiry_type_display()}"
