from django.db import models


class MedicineCatalog(models.Model):
    name = models.CharField(max_length=250, db_index=True)
    generic_name = models.CharField(max_length=250, db_index=True)
    form = models.CharField(max_length=30, blank=True)
    manufacturer = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=100, blank=True)

    class Meta:
        indexes = [models.Index(fields=['generic_name']), models.Index(fields=['name'])]

    def __str__(self):
        return f"{self.form} {self.name}".strip() if self.form else self.name


class PharmacyItem(models.Model):
    """Medicine master — one per drug per clinic."""
    clinic = models.ForeignKey('accounts.Clinic', on_delete=models.CASCADE, related_name='pharmacy_items')
    medicine = models.ForeignKey(MedicineCatalog, on_delete=models.CASCADE, null=True, blank=True)
    custom_name = models.CharField(max_length=250, blank=True)
    custom_generic_name = models.CharField(max_length=250, blank=True, help_text="Generic/active ingredient for custom medicines (e.g. Clindamycin 1% w/w)")
    reorder_level = models.PositiveIntegerField(default=10)
    reorder_flagged = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['clinic', 'medicine'])]

    @property
    def display_name(self):
        return self.medicine.name if self.medicine else self.custom_name

    @property
    def display_generic(self):
        """Generic/composition name — from catalog or custom entry."""
        if self.medicine:
            return self.medicine.generic_name
        return self.custom_generic_name

    @property
    def total_quantity(self):
        return sum(b.quantity for b in self.batches.all())

    @property
    def in_stock(self):
        return self.total_quantity > 0

    @property
    def low_stock(self):
        return 0 < self.total_quantity <= self.reorder_level

    @property
    def earliest_expiry(self):
        """Earliest expiry date among batches that have stock."""
        batches = [b for b in self.batches.all() if b.quantity > 0 and b.expiry_date]
        return min((b.expiry_date for b in batches), default=None)

    @property
    def use_first_batch(self):
        """The batch to dispense first (FEFO — soonest expiry with stock)."""
        batches = [b for b in self.batches.all() if b.quantity > 0 and b.expiry_date]
        return min(batches, key=lambda b: b.expiry_date, default=None)

    def __str__(self):
        return self.display_name


class PharmacyBatch(models.Model):
    """One purchase lot for a medicine."""
    item = models.ForeignKey(PharmacyItem, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=50, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    received_date = models.DateField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expiry_date']  # FEFO order

    @property
    def is_near_expiry(self):
        if not self.expiry_date:
            return False
        from django.utils import timezone
        return (self.expiry_date - timezone.now().date()).days <= 90

    @property
    def is_approaching_expiry(self):
        """Expiring in 3–6 months — orange warning tier."""
        if not self.expiry_date:
            return False
        from django.utils import timezone
        days = (self.expiry_date - timezone.now().date()).days
        return 90 < days <= 180

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        from django.utils import timezone
        return self.expiry_date < timezone.now().date()

    def __str__(self):
        return f"{self.item.display_name} — Batch {self.batch_number or 'N/A'}"


class DispensedItem(models.Model):
    """One line item dispensed to a patient for a visit."""
    visit = models.ForeignKey('reception.Visit', on_delete=models.CASCADE, related_name='dispensed_items')
    prescription_med = models.ForeignKey(
        'prescription.PrescriptionMedicine', on_delete=models.SET_NULL, null=True, blank=True
    )
    pharmacy_item = models.ForeignKey(PharmacyItem, on_delete=models.PROTECT)
    batch = models.ForeignKey(PharmacyBatch, on_delete=models.PROTECT)
    quantity_dispensed = models.PositiveIntegerField()
    quantity_returned = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    is_substitute = models.BooleanField(default=False)
    notes = models.CharField(max_length=200, blank=True)
    dispensed_by = models.ForeignKey('accounts.StaffMember', on_delete=models.SET_NULL, null=True)
    dispensed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.pharmacy_item.display_name} x{self.quantity_dispensed} — Visit {self.visit_id}"


class PharmacyBill(models.Model):
    """Final bill for a visit's dispensed medicines."""
    PAYMENT_CHOICES = [('cash', 'Cash'), ('card', 'Card'), ('upi', 'UPI')]
    visit = models.OneToOneField('reception.Visit', on_delete=models.CASCADE, related_name='pharmacy_bill')
    clinic = models.ForeignKey('accounts.Clinic', on_delete=models.CASCADE)
    bill_number = models.CharField(max_length=30, unique=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_percent = models.PositiveSmallIntegerField(default=0)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default='cash')
    created_by = models.ForeignKey('accounts.StaffMember', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def generate_bill_number(clinic_id):
        from django.utils import timezone
        today = timezone.localdate().strftime('%Y%m%d')
        prefix = f"BILL-{today}-"
        existing = PharmacyBill.objects.filter(
            bill_number__startswith=prefix
        ).values_list('bill_number', flat=True)
        if existing:
            seq = max(int(n[len(prefix):]) for n in existing) + 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    def __str__(self):
        return f"{self.bill_number} — {self.visit.patient.full_name}"


class DoctorFavorite(models.Model):
    doctor = models.ForeignKey('accounts.StaffMember', on_delete=models.CASCADE, related_name='favorite_medicines')
    medicine = models.ForeignKey(MedicineCatalog, on_delete=models.CASCADE, null=True, blank=True)
    custom_name = models.CharField(max_length=250, blank=True)
    default_form = models.CharField(max_length=30, blank=True)
    default_dosage = models.CharField(max_length=50, blank=True)
    default_frequency = models.CharField(max_length=100, blank=True)
    default_duration = models.CharField(max_length=50, blank=True)
    default_notes = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'created_at']

    @property
    def display_name(self):
        return self.medicine.name if self.medicine else self.custom_name

    def __str__(self):
        return self.display_name
