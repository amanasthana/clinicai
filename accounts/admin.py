from django.contrib import admin
from .models import Clinic, StaffMember, ClinicRegistrationRequest, ContactMessage, ClinicAIExecutive


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'phone', 'staff_count', 'patient_count', 'created_at')
    search_fields = ('name', 'city', 'phone')
    list_filter = ('state', 'city')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    def staff_count(self, obj):
        return obj.staff.count()
    staff_count.short_description = 'Staff'

    def patient_count(self, obj):
        return obj.patients.count()
    patient_count.short_description = 'Patients'


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'role', 'clinic', 'qualification', 'created_at')
    search_fields = ('display_name', 'user__username', 'clinic__name')
    list_filter = ('role', 'clinic')
    readonly_fields = ('created_at',)
    ordering = ('clinic', 'role')


@admin.register(ClinicRegistrationRequest)
class ClinicRegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('clinic_name', 'doctor_name', 'city', 'state', 'phone', 'referred_by_mobile', 'status', 'created_at')
    search_fields = ('clinic_name', 'doctor_name', 'phone', 'email', 'referred_by_mobile')
    list_filter = ('status', 'state', 'clinic_type')
    readonly_fields = ('created_at', 'reviewed_at', 'password_hash')
    ordering = ('-created_at',)


@admin.register(ClinicAIExecutive)
class ClinicAIExecutiveAdmin(admin.ModelAdmin):
    list_display = ('name', 'mobile', 'city', 'state', 'status', 'created_at')
    search_fields = ('name', 'mobile', 'city')
    list_filter = ('status', 'state', 'gender')
    readonly_fields = ('mobile', 'aadhaar_last4', 'aadhaar_hash', 'created_at')
    ordering = ('-created_at',)
    actions = ['approve_executives', 'reject_executives']

    def approve_executives(self, request, queryset):
        from django.utils import timezone as _tz
        queryset.update(status='approved', approved_at=_tz.now())
    approve_executives.short_description = 'Approve selected executives'

    def reject_executives(self, request, queryset):
        queryset.update(status='rejected')
    reject_executives.short_description = 'Reject selected executives'


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'inquiry_type', 'read', 'created_at')
    search_fields = ('name', 'email', 'phone', 'message')
    list_filter = ('inquiry_type', 'read')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
