import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Q

from .models import MedicineCatalog, PharmacyItem, DoctorFavorite


def _get_clinic(request):
    return request.user.staff_profile.clinic


@login_required
def pharmacy_dashboard(request):
    clinic = _get_clinic(request)
    items = PharmacyItem.objects.filter(clinic=clinic).select_related('medicine').order_by('medicine__name', 'custom_name')
    low_stock_items = [i for i in items if i.low_stock]
    out_of_stock_items = [i for i in items if not i.in_stock]
    total_in_stock = items.filter(quantity__gt=0).count()
    low_stock_count = len(low_stock_items)

    return render(request, 'pharmacy/dashboard.html', {
        'items': items,
        'low_stock_items': low_stock_items,
        'out_of_stock_items': out_of_stock_items,
        'total_in_stock': total_in_stock,
        'low_stock_count': low_stock_count,
    })


@login_required
def add_stock_view(request):
    clinic = _get_clinic(request)

    if request.method == 'POST':
        catalog_id = request.POST.get('catalog_id')
        custom_name = request.POST.get('custom_name', '').strip()
        batch_number = request.POST.get('batch_number', '').strip()
        expiry_date = request.POST.get('expiry_date') or None
        quantity = int(request.POST.get('quantity', 0) or 0)
        unit_price = request.POST.get('unit_price', '0') or '0'
        reorder_level = int(request.POST.get('reorder_level', 10) or 10)

        medicine = None
        if catalog_id:
            try:
                medicine = MedicineCatalog.objects.get(pk=catalog_id)
            except MedicineCatalog.DoesNotExist:
                pass

        if not medicine and not custom_name:
            return render(request, 'pharmacy/add_stock.html', {
                'error': 'Please select a medicine from catalog or enter a custom name.'
            })

        PharmacyItem.objects.create(
            clinic=clinic,
            medicine=medicine,
            custom_name=custom_name if not medicine else '',
            batch_number=batch_number,
            expiry_date=expiry_date,
            quantity=quantity,
            unit_price=unit_price,
            reorder_level=reorder_level,
        )
        return redirect('pharmacy:dashboard')

    return render(request, 'pharmacy/add_stock.html', {})


@login_required
def edit_stock_view(request, pk):
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)

    if request.method == 'POST':
        item.batch_number = request.POST.get('batch_number', '').strip()
        item.expiry_date = request.POST.get('expiry_date') or None
        item.quantity = int(request.POST.get('quantity', 0) or 0)
        item.unit_price = request.POST.get('unit_price', '0') or '0'
        item.reorder_level = int(request.POST.get('reorder_level', 10) or 10)
        item.save()
        return redirect('pharmacy:dashboard')

    return render(request, 'pharmacy/edit_stock.html', {'item': item})


@login_required
@require_POST
def delete_stock_view(request, pk):
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)
    item.delete()
    return redirect('pharmacy:dashboard')


@login_required
@require_POST
def flag_reorder_view(request, pk):
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)
    item.reorder_flagged = not item.reorder_flagged
    item.save(update_fields=['reorder_flagged'])
    return redirect('pharmacy:dashboard')


@login_required
def pharmacy_search_api(request):
    """JSON search inventory for this clinic."""
    clinic = _get_clinic(request)
    q = request.GET.get('q', '').strip()
    if len(q) < 1:
        return JsonResponse({'items': []})
    qs = PharmacyItem.objects.filter(clinic=clinic).filter(
        Q(medicine__name__icontains=q) | Q(custom_name__icontains=q)
    ).select_related('medicine')[:20]
    results = [
        {
            'id': item.pk,
            'name': item.display_name,
            'quantity': item.quantity,
            'unit_price': str(item.unit_price),
            'in_stock': item.in_stock,
        }
        for item in qs
    ]
    return JsonResponse({'items': results})


@login_required
def catalog_search_api(request):
    """JSON search MedicineCatalog (for add stock & favorites)."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'items': []})
    qs = MedicineCatalog.objects.filter(
        Q(name__icontains=q) | Q(generic_name__icontains=q)
    )[:20]
    results = [
        {
            'id': m.pk,
            'name': m.name,
            'generic_name': m.generic_name,
            'form': m.form,
            'manufacturer': m.manufacturer,
            'category': m.category,
        }
        for m in qs
    ]
    return JsonResponse({'items': results})
