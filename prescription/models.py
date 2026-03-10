import uuid
from django.db import models


class Prescription(models.Model):
    """
    AI-generated prescription linked to a visit.

    Privacy note: raw_clinical_note stores the doctor's original text.
    The AI NEVER receives patient PII — de-identification happens in services.py
    before any API call. See DATA FLOW in services.py for details.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visit = models.OneToOneField(
        'reception.Visit', on_delete=models.CASCADE, related_name='prescription'
    )
    doctor = models.ForeignKey(
        'accounts.StaffMember', on_delete=models.SET_NULL, null=True
    )
    # Doctor's raw clinical input (stored in our DB, encrypted at rest via Azure)
    raw_clinical_note = models.TextField()
    # AI-generated outputs
    soap_note = models.TextField(blank=True)
    diagnosis = models.CharField(max_length=500, blank=True)
    advice = models.TextField(blank=True)
    patient_summary_en = models.TextField(blank=True)
    patient_summary_hi = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    # Differential diagnosis workflow fields
    differential_diagnoses = models.JSONField(null=True, blank=True)  # [{rank, diagnosis, probability, reasoning, red_flags}]
    investigations = models.JSONField(null=True, blank=True)          # {immediate: [...], elective: [...]}
    selected_diagnosis = models.CharField(max_length=500, blank=True) # doctor's confirmed choice from differentials
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rx — {self.visit.patient.full_name} ({self.created_at.date()})"


class PrescriptionMedicine(models.Model):
    """One line item in a prescription (one drug per row)."""
    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name='medicines'
    )
    drug_name = models.CharField(max_length=200)    # "Tab Metformin 500mg"
    dosage = models.CharField(max_length=100)        # "1-0-1"
    frequency = models.CharField(max_length=100)     # "Twice daily after meals"
    duration = models.CharField(max_length=50)       # "14 days"
    notes = models.CharField(max_length=200, blank=True)  # "Take with food"
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.drug_name} — {self.dosage} for {self.duration}"


class MedicalTerm(models.Model):
    CATEGORY_CHOICES = [
        ('symptom', 'Symptom'),
        ('diagnosis', 'Diagnosis'),
        ('investigation', 'Investigation'),
        ('procedure', 'Procedure'),
        ('medicine', 'Medicine'),
        ('advice', 'Advice'),
        ('snippet', 'Snippet'),
        ('abbreviation', 'Abbreviation'),
    ]
    term = models.CharField(max_length=300, db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    aliases = models.TextField(blank=True)
    specialty = models.CharField(max_length=50, blank=True)
    icd_code = models.CharField(max_length=20, blank=True)
    weight = models.PositiveSmallIntegerField(
        default=50,
        help_text="Higher = surfaces first. Common terms get 90-100, rare ones 10-20."
    )

    class Meta:
        indexes = [
            models.Index(fields=['category', 'term']),
            models.Index(fields=['specialty', 'term']),
        ]

    def __str__(self):
        return f"{self.term} ({self.category})"
