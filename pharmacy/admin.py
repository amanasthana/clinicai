from django.contrib import admin
from .models import MedicineCatalog, PharmacyItem, PharmacyBatch, DoctorFavorite


@admin.register(MedicineCatalog)
class MedicineCatalogAdmin(admin.ModelAdmin):
    list_display = ('name', 'generic_name', 'form', 'manufacturer', 'category')
    search_fields = ('name', 'generic_name', 'manufacturer')
    list_filter = ('form', 'category')
    ordering = ('name',)


class PharmacyBatchInline(admin.TabularInline):
    model = PharmacyBatch
    extra = 1
    fields = ('batch_number', 'expiry_date', 'quantity', 'unit_price', 'received_date')
    readonly_fields = ('received_date',)


@admin.register(PharmacyItem)
class PharmacyItemAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'clinic', 'total_quantity', 'reorder_level', 'reorder_flagged', 'updated_at')
    search_fields = ('medicine__name', 'custom_name')
    list_filter = ('clinic', 'reorder_flagged')
    ordering = ('-updated_at',)
    inlines = [PharmacyBatchInline]

    def display_name(self, obj):
        return obj.display_name
    display_name.short_description = 'Medicine'

    def total_quantity(self, obj):
        return obj.total_quantity
    total_quantity.short_description = 'Total Qty'


@admin.register(PharmacyBatch)
class PharmacyBatchAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'batch_number', 'quantity', 'unit_price', 'expiry_date', 'received_date')
    search_fields = ('item__medicine__name', 'item__custom_name', 'batch_number')
    list_filter = ('item__clinic',)
    ordering = ('expiry_date',)


@admin.register(DoctorFavorite)
class DoctorFavoriteAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'doctor', 'default_dosage', 'default_frequency', 'default_duration', 'sort_order')
    search_fields = ('medicine__name', 'custom_name', 'doctor__display_name')
    list_filter = ('doctor',)
    ordering = ('doctor', 'sort_order')

    def display_name(self, obj):
        return obj.display_name
    display_name.short_description = 'Medicine'
