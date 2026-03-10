from django.contrib import admin
from .models import MedicineCatalog, PharmacyItem, DoctorFavorite


@admin.register(MedicineCatalog)
class MedicineCatalogAdmin(admin.ModelAdmin):
    list_display = ('name', 'generic_name', 'form', 'manufacturer', 'category')
    search_fields = ('name', 'generic_name', 'manufacturer')
    list_filter = ('form', 'category')
    ordering = ('name',)


@admin.register(PharmacyItem)
class PharmacyItemAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'clinic', 'quantity', 'unit_price', 'expiry_date', 'reorder_flagged', 'updated_at')
    search_fields = ('medicine__name', 'custom_name', 'batch_number')
    list_filter = ('clinic', 'reorder_flagged')
    ordering = ('-updated_at',)

    def display_name(self, obj):
        return obj.display_name
    display_name.short_description = 'Medicine'


@admin.register(DoctorFavorite)
class DoctorFavoriteAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'doctor', 'default_dosage', 'default_frequency', 'default_duration', 'sort_order')
    search_fields = ('medicine__name', 'custom_name', 'doctor__display_name')
    list_filter = ('doctor',)
    ordering = ('doctor', 'sort_order')

    def display_name(self, obj):
        return obj.display_name
    display_name.short_description = 'Medicine'
