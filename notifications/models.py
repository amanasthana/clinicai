"""Stub models for future notifications module (Phase 3)."""
from django.db import models


class NotificationLog(models.Model):
    """Tracks WhatsApp/SMS notifications sent to patients (stub)."""
    CHANNEL_CHOICES = [('whatsapp', 'WhatsApp'), ('sms', 'SMS')]
    STATUS_CHOICES = [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')]

    visit = models.ForeignKey('reception.Visit', on_delete=models.CASCADE)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default='whatsapp')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class UserNotice(models.Model):
    """A one-time in-app announcement for a staff user (e.g. the MedlynAI rebrand).

    A row means the user should see notice `key`; it is shown on every page
    until they dismiss it, which sets seen_at.
    """
    REBRAND_MEDLYNAI = 'rebrand-medlynai'

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='notices')
    key = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'key'], name='unique_user_notice'),
        ]

    def __str__(self):
        return f"{self.key} → {self.user.username} ({'seen' if self.seen_at else 'pending'})"
