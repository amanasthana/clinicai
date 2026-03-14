import json
import re
import decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.db.models import Q
from django.db import transaction

from accounts.permissions import require_permission
from .models import MedicineCatalog, PharmacyItem, PharmacyBatch, DoctorFavorite, DispensedItem, PharmacyBill


def _get_clinic(request):
    return request.user.staff_profile.clinic


@require_permission('can_view_pharmacy')
def pharmacy_dashboard(request):
    clinic = _get_clinic(request)

    # Pending dispense: visits marked done today without a bill
    from reception.models import Visit
    from django.utils import timezone as tz
    today = tz.now().date()
    pending_dispense = (
        Visit.objects
        .filter(clinic=clinic, visit_date=today, status='done')
        .exclude(pharmacy_bill__isnull=False)
        .select_related('patient')
        .prefetch_related('prescription__doctor')
        .order_by('token_number')
    )

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

    import datetime
    from django.utils import timezone as tz
    today = tz.now().date()
    today_plus_90 = (today + datetime.timedelta(days=90)).strftime('%Y-%m-%d')
    expiring_3m_count = 0
    expiring_6m_count = 0
    for item in items:
        for batch in item.batches.all():
            if batch.quantity > 0 and batch.expiry_date:
                days = (batch.expiry_date - today).days
                if 0 < days <= 90:
                    expiring_3m_count += 1
                elif 90 < days <= 180:
                    expiring_6m_count += 1

    return render(request, 'pharmacy/dashboard.html', {
        'items': items,
        'low_stock_items': low_stock_items,
        'out_of_stock_items': out_of_stock_items,
        'total_in_stock': total_in_stock,
        'low_stock_count': low_stock_count,
        'expiring_3m_count': expiring_3m_count,
        'expiring_6m_count': expiring_6m_count,
        'today_plus_90': today_plus_90,
        'pending_dispense': pending_dispense,
    })


@require_permission('can_edit_inventory')
def add_stock_view(request):
    clinic = _get_clinic(request)

    if request.method == 'POST':
        catalog_id = request.POST.get('catalog_id')
        custom_name = request.POST.get('custom_name', '').strip()
        custom_generic_name = request.POST.get('custom_generic_name', '').strip()
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
            # Update generic name if provided and item is custom
            if not existing_item.medicine and custom_generic_name:
                existing_item.custom_generic_name = custom_generic_name
            existing_item.save(update_fields=['reorder_level', 'custom_generic_name', 'updated_at'])
        else:
            # Create new medicine master + first batch
            item = PharmacyItem.objects.create(
                clinic=clinic,
                medicine=medicine,
                custom_name=custom_name if not medicine else '',
                custom_generic_name=custom_generic_name if not medicine else '',
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


@require_permission('can_edit_inventory')
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


@require_permission('can_edit_inventory')
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
        # Also save generic composition on the item if it's a custom medicine
        if not batch.item.medicine:
            custom_generic_name = request.POST.get('custom_generic_name', '').strip()
            batch.item.custom_generic_name = custom_generic_name
            batch.item.save(update_fields=['custom_generic_name', 'updated_at'])
        return redirect('pharmacy:dashboard')

    return render(request, 'pharmacy/edit_batch.html', {'batch': batch})


@require_permission('can_edit_inventory')
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


@require_permission('can_edit_inventory')
def edit_item_view(request, pk):
    """Edit a PharmacyItem's name, generic composition, and reorder level."""
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)

    if request.method == 'POST':
        reorder_level = int(request.POST.get('reorder_level', 0) or 0)
        item.reorder_level = reorder_level
        # Only custom medicines (no catalog link) can have their name/generic edited
        if not item.medicine:
            custom_name = request.POST.get('custom_name', '').strip()
            custom_generic_name = request.POST.get('custom_generic_name', '').strip()
            if custom_name:
                item.custom_name = custom_name
            item.custom_generic_name = custom_generic_name
        item.save()
        return redirect('pharmacy:dashboard')

    return render(request, 'pharmacy/edit_stock.html', {'item': item})


@require_permission('can_edit_inventory')
@require_POST
def delete_item_view(request, pk):
    """Delete a PharmacyItem (and all its batches via CASCADE)."""
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)
    item.delete()
    return redirect('pharmacy:dashboard')


@require_permission('can_edit_inventory')
@require_POST
def flag_reorder_view(request, pk):
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)
    item.reorder_flagged = not item.reorder_flagged
    item.save(update_fields=['reorder_flagged', 'updated_at'])
    return redirect('pharmacy:dashboard')


@require_permission('can_view_pharmacy')
def pharmacy_search_api(request):
    """JSON search inventory for this clinic."""
    clinic = _get_clinic(request)
    q = request.GET.get('q', '').strip()
    if len(q) < 1:
        return JsonResponse({'items': []})
    qs = (
        PharmacyItem.objects
        .filter(clinic=clinic)
        .filter(
            Q(medicine__name__icontains=q) |
            Q(medicine__generic_name__icontains=q) |
            Q(custom_name__icontains=q) |
            Q(custom_generic_name__icontains=q)
        )
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


@require_permission('can_view_pharmacy')
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


# ---------------------------------------------------------------------------
# Helper: calculate suggested quantity from dosage + duration strings
# ---------------------------------------------------------------------------

def _calc_qty(dosage, duration):
    """
    Calculate suggested quantity to dispense based on dosage schedule and duration.
    dosage:   e.g. "1-0-1" or "1-1-1"
    duration: e.g. "5 days", "2 weeks", "1 month", "10 din"
    """
    parts = [p.strip() for p in dosage.split('-')]
    per_day = sum(int(p) for p in parts if p.isdigit())
    days = 0
    dur_lower = (duration or '').lower()
    m = re.search(r'(\d+)\s*(?:day|din)', dur_lower)
    if m:
        days = int(m.group(1))
    else:
        m = re.search(r'(\d+)\s*week', dur_lower)
        if m:
            days = int(m.group(1)) * 7
        else:
            m = re.search(r'(\d+)\s*month', dur_lower)
            if m:
                days = int(m.group(1)) * 30
    if per_day > 0 and days > 0:
        return per_day * days
    return 1


# ---------------------------------------------------------------------------
# Dispense view
# ---------------------------------------------------------------------------

@require_permission('can_dispense_bill')
def dispense_view(request, visit_id):
    """GET only. Shows the dispensing screen for a visit."""
    from reception.models import Visit

    clinic = _get_clinic(request)
    visit = get_object_or_404(Visit, id=visit_id, clinic=clinic)

    # Load prescription if it exists
    existing_rx = getattr(visit, 'prescription', None)

    medicine_rows = []
    if existing_rx:
        for pm in existing_rx.medicines.all():
            suggested_qty = _calc_qty(pm.dosage, pm.duration)
            # Try to match pharmacy item by name (case-insensitive)
            drug_name_clean = pm.drug_name.strip()
            item = (
                PharmacyItem.objects
                .filter(clinic=clinic)
                .filter(
                    Q(medicine__name__iexact=drug_name_clean) |
                    Q(custom_name__iexact=drug_name_clean) |
                    Q(medicine__name__icontains=drug_name_clean) |
                    Q(custom_name__icontains=drug_name_clean)
                )
                .select_related('medicine')
                .prefetch_related('batches')
                .first()
            )
            batch = item.use_first_batch if item else None
            medicine_rows.append({
                'prescription_med_id': pm.pk,
                'drug_name': pm.drug_name,
                'dosage': pm.dosage,
                'duration': pm.duration,
                'suggested_qty': suggested_qty,
                'item_id': item.pk if item else None,
                'item_name': item.display_name if item else '',
                'batch_id': batch.pk if batch else None,
                'unit_price': str(batch.unit_price) if batch else '0',
                'stock_qty': batch.quantity if batch else 0,
                'in_stock': item.in_stock if item else False,
            })

    # Also build a list of all pharmacy items for manual addition
    all_items = (
        PharmacyItem.objects.filter(clinic=clinic)
        .select_related('medicine')
        .prefetch_related('batches')
        .order_by('medicine__name', 'custom_name')
    )

    # Check if already billed
    already_billed = hasattr(visit, 'pharmacy_bill')

    return render(request, 'pharmacy/dispense.html', {
        'visit': visit,
        'patient': visit.patient,
        'existing_rx': existing_rx,
        'medicine_rows': medicine_rows,
        'all_items': all_items,
        'already_billed': already_billed,
    })


# ---------------------------------------------------------------------------
# Confirm dispense API (POST JSON)
# ---------------------------------------------------------------------------

@require_permission('can_dispense_bill')
def confirm_dispense_api(request, visit_id):
    """POST JSON. Creates DispensedItem records, decrements stock, creates bill."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    from reception.models import Visit

    clinic = _get_clinic(request)
    visit = get_object_or_404(Visit, id=visit_id, clinic=clinic)

    # Prevent double billing
    if hasattr(visit, 'pharmacy_bill'):
        return JsonResponse({'ok': False, 'error': 'This visit already has a bill.'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    items_data = data.get('items', [])
    discount_percent = int(data.get('discount', 0) or 0)
    payment_mode = data.get('payment_mode', 'cash')

    if not items_data:
        return JsonResponse({'ok': False, 'error': 'No items to dispense.'}, status=400)

    # Validate all items before writing anything
    for item_data in items_data:
        batch_id = item_data.get('batch_id')
        qty = int(item_data.get('qty', 0) or 0)
        if not batch_id or qty <= 0:
            return JsonResponse({'ok': False, 'error': 'Invalid item data.'}, status=400)
        batch = get_object_or_404(PharmacyBatch, pk=batch_id, item__clinic=clinic)
        if batch.quantity < qty:
            return JsonResponse({
                'ok': False,
                'error': f'Not enough stock for {batch.item.display_name}. Available: {batch.quantity}'
            }, status=400)

    # All validations passed — write atomically
    with transaction.atomic():
        subtotal = decimal.Decimal('0.00')

        for item_data in items_data:
            batch_id = item_data['batch_id']
            qty = int(item_data['qty'])
            prescription_med_id = item_data.get('prescription_med_id')
            is_substitute = bool(item_data.get('is_substitute', False))
            notes = (item_data.get('notes') or '')[:200]

            batch = PharmacyBatch.objects.select_for_update().get(pk=batch_id)
            pharmacy_item = batch.item
            unit_price = batch.unit_price

            # Decrement stock
            batch.quantity -= qty
            batch.save(update_fields=['quantity', 'updated_at'])

            DispensedItem.objects.create(
                visit=visit,
                prescription_med_id=prescription_med_id or None,
                pharmacy_item=pharmacy_item,
                batch=batch,
                quantity_dispensed=qty,
                unit_price=unit_price,
                is_substitute=is_substitute,
                notes=notes,
                dispensed_by=request.user.staff_profile,
            )
            subtotal += unit_price * qty

        # Calculate final amount
        discount_amount = subtotal * discount_percent / 100
        final_amount = subtotal - discount_amount

        bill = PharmacyBill.objects.create(
            visit=visit,
            clinic=clinic,
            bill_number=PharmacyBill.generate_bill_number(clinic.pk),
            subtotal=subtotal,
            discount_percent=discount_percent,
            final_amount=final_amount,
            payment_mode=payment_mode,
            created_by=request.user.staff_profile,
        )

    return JsonResponse({'ok': True, 'bill_id': bill.pk})


# ---------------------------------------------------------------------------
# Bill view
# ---------------------------------------------------------------------------

@require_permission('can_dispense_bill')
def bill_view(request, bill_id):
    """GET. Shows a printable bill/receipt."""
    clinic = _get_clinic(request)
    bill = get_object_or_404(PharmacyBill, pk=bill_id, clinic=clinic)
    dispensed_items = bill.visit.dispensed_items.select_related('pharmacy_item', 'pharmacy_item__medicine', 'batch').all()
    return render(request, 'pharmacy/bill.html', {
        'bill': bill,
        'visit': bill.visit,
        'patient': bill.visit.patient,
        'clinic': clinic,
        'dispensed_items': dispensed_items,
    })


# ---------------------------------------------------------------------------
# Alternatives API
# ---------------------------------------------------------------------------

@require_permission('can_view_pharmacy')
def alternatives_api(request, item_id):
    """GET JSON. Returns other PharmacyItems with the same generic that have stock."""
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=item_id, clinic=clinic)

    generic = item.display_generic  # could be empty

    results = []
    if generic:
        qs = (
            PharmacyItem.objects.filter(clinic=clinic)
            .exclude(pk=item_id)
            .filter(
                Q(medicine__generic_name__iexact=generic) |
                Q(custom_generic_name__iexact=generic)
            )
            .select_related('medicine')
            .prefetch_related('batches')
        )
        for alt in qs:
            if alt.in_stock:
                fefo = alt.use_first_batch
                results.append({
                    'id': alt.pk,
                    'name': alt.display_name,
                    'generic': alt.display_generic,
                    'stock_qty': alt.total_quantity,
                    'unit_price': str(fefo.unit_price) if fefo else '0',
                    'batch_id': fefo.pk if fefo else None,
                    'expiry': fefo.expiry_date.strftime('%Y-%m') if fefo and fefo.expiry_date else None,
                })

    # Fallback: fuzzy name match if no generic results
    if not results:
        item_name = item.display_name.lower()
        # Use first significant word (skip common prefixes like Tab/Cap/Syp)
        words = [w for w in item_name.split() if w not in ('tab', 'cap', 'syp', 'inj', 'oint', 'gel', 'drop')]
        if words:
            search_term = words[0]
            qs2 = (
                PharmacyItem.objects.filter(clinic=clinic)
                .exclude(pk=item_id)
                .filter(
                    Q(medicine__name__icontains=search_term) |
                    Q(custom_name__icontains=search_term)
                )
                .select_related('medicine')
                .prefetch_related('batches')
            )
            for alt in qs2:
                if alt.in_stock:
                    fefo = alt.use_first_batch
                    results.append({
                        'id': alt.pk,
                        'name': alt.display_name,
                        'generic': alt.display_generic,
                        'stock_qty': alt.total_quantity,
                        'unit_price': str(fefo.unit_price) if fefo else '0',
                        'batch_id': fefo.pk if fefo else None,
                        'expiry': fefo.expiry_date.strftime('%Y-%m') if fefo and fefo.expiry_date else None,
                    })

    # Sort by expiry ascending (FEFO)
    results.sort(key=lambda x: x['expiry'] or '9999-99')

    return JsonResponse({'alternatives': results})


# ---------------------------------------------------------------------------
# Add stock via bill scan
# ---------------------------------------------------------------------------

@require_permission('can_edit_inventory')
def add_stock_scan_view(request):
    """GET only — renders the scan upload page. Actual scanning is done by prescription scan_bill_api."""
    return render(request, 'pharmacy/add_stock_scan.html')
