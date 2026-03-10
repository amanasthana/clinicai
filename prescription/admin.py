from django.contrib import admin
from .models import Prescription, PrescriptionMedicine, MedicalTerm


class PrescriptionMedicineInline(admin.TabularInline):
    model = PrescriptionMedicine
    extra = 0
    fields = ('order', 'drug_name', 'dosage', 'frequency', 'duration', 'notes')
    ordering = ('order',)


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ('patient_name', 'clinic_name', 'diagnosis', 'doctor', 'medicine_count', 'created_at')
    search_fields = ('visit__patient__full_name', 'visit__clinic__name', 'diagnosis', 'doctor__display_name')
    list_filter = ('visit__clinic', 'doctor', 'created_at')
    readonly_fields = ('id', 'created_at', 'raw_clinical_note', 'differential_diagnoses', 'investigations', 'selected_diagnosis')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    inlines = [PrescriptionMedicineInline]

    def patient_name(self, obj):
        return obj.visit.patient.full_name
    patient_name.short_description = 'Patient'

    def clinic_name(self, obj):
        return obj.visit.clinic.name
    clinic_name.short_description = 'Clinic'

    def medicine_count(self, obj):
        return obj.medicines.count()
    medicine_count.short_description = 'Medicines'


@admin.register(MedicalTerm)
class MedicalTermAdmin(admin.ModelAdmin):
    list_display = ('term', 'category', 'specialty', 'icd_code')
    search_fields = ('term', 'aliases', 'icd_code')
    list_filter = ('category', 'specialty')
    ordering = ('category', 'term')
