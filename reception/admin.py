from django.contrib import admin
from .models import Patient, Visit


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'age', 'gender', 'clinic', 'blood_group', 'visit_count', 'created_at')
    search_fields = ('full_name', 'phone', 'clinic__name')
    list_filter = ('clinic', 'gender', 'blood_group')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)

    def visit_count(self, obj):
        return obj.visits.count()
    visit_count.short_description = 'Visits'


class VisitInline(admin.TabularInline):
    model = Visit
    extra = 0
    fields = ('visit_date', 'token_number', 'chief_complaint', 'status', 'vitals_bp', 'vitals_spo2')
    readonly_fields = ('visit_date', 'token_number', 'created_at')
    ordering = ('-visit_date',)
    show_change_link = True


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ('patient', 'clinic', 'token_number', 'visit_date', 'chief_complaint', 'status', 'has_prescription')
    search_fields = ('patient__full_name', 'patient__phone', 'clinic__name', 'chief_complaint')
    list_filter = ('clinic', 'status', 'visit_date')
    readonly_fields = ('id', 'created_at', 'called_at', 'completed_at')
    ordering = ('-visit_date', 'token_number')
    date_hierarchy = 'visit_date'

    def has_prescription(self, obj):
        return hasattr(obj, 'prescription')
    has_prescription.boolean = True
    has_prescription.short_description = 'Rx'
