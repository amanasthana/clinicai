"""Stub models for future pharmacy module (Phase 3)."""
from django.db import models


class Medicine(models.Model):
    """Pharmacy inventory stub. Full implementation in Phase 3."""
    clinic = models.ForeignKey('accounts.Clinic', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)          # "Tab Metformin 500mg"
    batch_number = models.CharField(max_length=50, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity_in_stock = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.name
