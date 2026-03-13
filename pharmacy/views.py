import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import Q

from .models import MedicineCatalog, PharmacyItem, PharmacyBatch, DoctorFavorite


def _get_clinic(request):
    return request.user.staff_profile.clinic


@login_required
def pharmacy_dashboard(request):
    clinic = _get_clinic(request)
    items = (
        PharmacyItem.objects
        .filter(clinic=clinic)
        .select_related('medicine')
        .prefetch_related('batches')
        .order_by('medicine__name', 'custom_name')
    )

    low_stock_items = [i for i in items if i.low_stock]
    out_of_stock_items = [i for i in items if not i.in_stock]
    total_in_stock = sum(1 for i in items if i.in_stock)
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

        # Check if this medicine already exists in the clinic's inventory
        existing_item = None
        if medicine:
            existing_item = PharmacyItem.objects.filter(clinic=clinic, medicine=medicine).first()
        elif custom_name:
            existing_item = PharmacyItem.objects.filter(clinic=clinic, custom_name=custom_name).first()

        if existing_item:
            # Add a new batch to the existing item
            PharmacyBatch.objects.create(
                item=existing_item,
                batch_number=batch_number,
                expiry_date=expiry_date,
                quantity=quantity,
                unit_price=unit_price,
            )
            existing_item.reorder_level = reorder_level
            existing_item.save(update_fields=['reorder_level', 'updated_at'])
        else:
            # Create new medicine master + first batch
            item = PharmacyItem.objects.create(
                clinic=clinic,
                medicine=medicine,
                custom_name=custom_name if not medicine else '',
                reorder_level=reorder_level,
            )
            PharmacyBatch.objects.create(
                item=item,
                batch_number=batch_number,
                expiry_date=expiry_date,
                quantity=quantity,
                unit_price=unit_price,
            )

        return redirect('pharmacy:dashboard')

    # On GET: check if the URL has an item_id shortcut (from "Add Batch" button)
    prefill_item = None
    item_id = request.GET.get('item_id')
    if item_id:
        prefill_item = PharmacyItem.objects.filter(pk=item_id, clinic=clinic).select_related('medicine').first()

    return render(request, 'pharmacy/add_stock.html', {'prefill_item': prefill_item})


@login_required
def add_batch_view(request, pk):
    """POST only — adds a new batch to an existing PharmacyItem."""
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)

    if request.method == 'POST':
        batch_number = request.POST.get('batch_number', '').strip()
        expiry_date = request.POST.get('expiry_date') or None
        quantity = int(request.POST.get('quantity', 0) or 0)
        unit_price = request.POST.get('unit_price', '0') or '0'

        PharmacyBatch.objects.create(
            item=item,
            batch_number=batch_number,
            expiry_date=expiry_date,
            quantity=quantity,
            unit_price=unit_price,
        )
        return redirect('pharmacy:dashboard')

    # GET: show a small form pre-filled with the item
    return render(request, 'pharmacy/add_batch.html', {'item': item})


@login_required
def edit_batch_view(request, pk):
    """Edit a specific PharmacyBatch."""
    clinic = _get_clinic(request)
    batch = get_object_or_404(PharmacyBatch, pk=pk, item__clinic=clinic)

    if request.method == 'POST':
        batch.batch_number = request.POST.get('batch_number', '').strip()
        batch.expiry_date = request.POST.get('expiry_date') or None
        batch.quantity = int(request.POST.get('quantity', 0) or 0)
        batch.unit_price = request.POST.get('unit_price', '0') or '0'
        batch.save()
        return redirect('pharmacy:dashboard')

    return render(request, 'pharmacy/edit_batch.html', {'batch': batch})


@login_required
@require_POST
def delete_batch_view(request, pk):
    """Delete a PharmacyBatch. If the item has no remaining batches the item itself is also removed."""
    clinic = _get_clinic(request)
    batch = get_object_or_404(PharmacyBatch, pk=pk, item__clinic=clinic)
    item = batch.item
    batch.delete()
    # Clean up orphan medicine masters with no batches
    if not item.batches.exists():
        item.delete()
    return redirect('pharmacy:dashboard')


@login_required
@require_POST
def delete_item_view(request, pk):
    """Delete a PharmacyItem (and all its batches via CASCADE)."""
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
    item.save(update_fields=['reorder_flagged', 'updated_at'])
    return redirect('pharmacy:dashboard')


@login_required
def pharmacy_search_api(request):
    """JSON search inventory for this clinic."""
    clinic = _get_clinic(request)
    q = request.GET.get('q', '').strip()
    if len(q) < 1:
        return JsonResponse({'items': []})
    qs = (
        PharmacyItem.objects
        .filter(clinic=clinic)
        .filter(Q(medicine__name__icontains=q) | Q(custom_name__icontains=q))
        .select_related('medicine')
        .prefetch_related('batches')[:20]
    )
    results = [
        {
            'id': item.pk,
            'name': item.display_name,
            'quantity': item.total_quantity,
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
