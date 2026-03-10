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
    clinic = models.ForeignKey('accounts.Clinic', on_delete=models.CASCADE, related_name='pharmacy_items')
    medicine = models.ForeignKey(MedicineCatalog, on_delete=models.CASCADE, null=True, blank=True)
    custom_name = models.CharField(max_length=250, blank=True)
    batch_number = models.CharField(max_length=50, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reorder_level = models.PositiveIntegerField(default=10)
    reorder_flagged = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['clinic', 'medicine'])]

    @property
    def display_name(self):
        return self.medicine.name if self.medicine else self.custom_name

    @property
    def in_stock(self):
        return self.quantity > 0

    @property
    def low_stock(self):
        return 0 < self.quantity <= self.reorder_level

    def __str__(self):
        return self.display_name


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
