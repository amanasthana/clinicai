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

    # Pending dispense: all today's visits without a bill (any status except no_show/cancelled)
    from reception.models import Visit
    from django.utils import timezone as tz
    today = tz.now().date()
    pending_dispense = (
        Visit.objects
        .filter(clinic=clinic, visit_date=today)
        .exclude(status__in=['no_show', 'cancelled'])
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

    # Layer 1: batches with ₹0 price that still have stock — warn the pharmacist
    zero_price_batches = list(
        PharmacyBatch.objects
        .filter(item__clinic=clinic, unit_price=0, quantity__gt=0)
        .select_related('item__medicine')
        .order_by('item__medicine__name', 'item__custom_name')
    )

    return render(request, 'pharmacy/dashboard.html', {
        'items': items,
        'clinic': clinic,
        'low_stock_items': low_stock_items,
        'out_of_stock_items': out_of_stock_items,
        'total_in_stock': total_in_stock,
        'low_stock_count': low_stock_count,
        'expiring_3m_count': expiring_3m_count,
        'expiring_6m_count': expiring_6m_count,
        'today_plus_90': today_plus_90,
        'pending_dispense': pending_dispense,
        'zero_price_batches': zero_price_batches,
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
        unit_price_raw = request.POST.get('unit_price', '0') or '0'
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

        # Layer 3: reject zero/missing price at the server side
        try:
            unit_price_dec = decimal.Decimal(str(unit_price_raw))
        except decimal.InvalidOperation:
            unit_price_dec = decimal.Decimal('0')
        if unit_price_dec <= 0:
            return render(request, 'pharmacy/add_stock.html', {
                'error': 'Unit price (MRP per unit) must be greater than ₹0. '
                         'Medicines with no price will bill patients ₹0.',
            })
        unit_price = unit_price_raw

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
    suggested_price = ''
    item_id = request.GET.get('item_id')
    if item_id:
        prefill_item = PharmacyItem.objects.filter(pk=item_id, clinic=clinic).select_related('medicine').prefetch_related('batches').first()
        if prefill_item:
            last_batch = prefill_item.batches.order_by('-received_date', '-id').first()
            if last_batch and last_batch.unit_price > 0:
                suggested_price = str(last_batch.unit_price)

    return render(request, 'pharmacy/add_stock.html', {'prefill_item': prefill_item, 'suggested_price': suggested_price})


@require_permission('can_edit_inventory')
def add_batch_view(request, pk):
    """POST only — adds a new batch to an existing PharmacyItem."""
    clinic = _get_clinic(request)
    item = get_object_or_404(PharmacyItem, pk=pk, clinic=clinic)

    if request.method == 'POST':
        batch_number = request.POST.get('batch_number', '').strip()
        expiry_date = request.POST.get('expiry_date') or None
        quantity = int(request.POST.get('quantity', 0) or 0)
        unit_price_raw = request.POST.get('unit_price', '0') or '0'

        # Layer 3: reject zero/missing price
        try:
            unit_price_dec = decimal.Decimal(str(unit_price_raw))
        except decimal.InvalidOperation:
            unit_price_dec = decimal.Decimal('0')
        if unit_price_dec <= 0:
            return render(request, 'pharmacy/add_batch.html', {
                'item': item,
                'error': 'Unit price (MRP per unit) must be greater than ₹0. '
                         'Medicines with no price will bill patients ₹0.',
            })

        PharmacyBatch.objects.create(
            item=item,
            batch_number=batch_number,
            expiry_date=expiry_date,
            quantity=quantity,
            unit_price=unit_price_raw,
        )
        return redirect('pharmacy:dashboard')

    # GET: pre-fill price from most recently added batch so pharmacist doesn't re-type unchanged MRPs
    last_batch = item.batches.order_by('-received_date', '-id').first()
    suggested_price = str(last_batch.unit_price) if last_batch and last_batch.unit_price > 0 else ''
    return render(request, 'pharmacy/add_batch.html', {'item': item, 'suggested_price': suggested_price})


@require_permission('can_edit_inventory')
def edit_batch_view(request, pk):
    """Edit a specific PharmacyBatch."""
    clinic = _get_clinic(request)
    batch = get_object_or_404(PharmacyBatch, pk=pk, item__clinic=clinic)

    if request.method == 'POST':
        unit_price_raw = request.POST.get('unit_price', '0') or '0'

        # Layer 3: reject zero/missing price
        try:
            unit_price_dec = decimal.Decimal(str(unit_price_raw))
        except decimal.InvalidOperation:
            unit_price_dec = decimal.Decimal('0')
        if unit_price_dec <= 0:
            return render(request, 'pharmacy/edit_batch.html', {
                'batch': batch,
                'error': 'Unit price (MRP per unit) must be greater than ₹0. '
                         'Medicines with no price will bill patients ₹0.',
            })

        batch.batch_number = request.POST.get('batch_number', '').strip()
        batch.expiry_date = request.POST.get('expiry_date') or None
        batch.quantity = int(request.POST.get('quantity', 0) or 0)
        batch.unit_price = unit_price_raw
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

_UNIT_DISPENSE_KEYWORDS = re.compile(
    r'\b(syrup|ointment|cream|lotion|gel|drops|drop|suspension|solution|linctus|'
    r'emulsion|spray|inhaler|nebulization|patch|sachet|powder|dusting|liniment|oil)\b',
    re.IGNORECASE,
)


def _calc_qty(dosage, duration, drug_name=''):
    """
    Calculate suggested quantity to dispense based on dosage schedule and duration.
    dosage:    e.g. "1-0-1" or "1-1-1"
    duration:  e.g. "5 days", "2 weeks", "1 month", "10 din"
    drug_name: e.g. "Tab Metformin 500mg" or "Betnovate Cream" or "Cough Syrup"

    For unit-dispensed forms (syrup, ointment, cream, lotion, gel, drops, etc.)
    the quantity is always 1 — these come as a single bottle/tube/vial.
    """
    if drug_name and _UNIT_DISPENSE_KEYWORDS.search(drug_name):
        return 1

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
            suggested_qty = _calc_qty(pm.dosage, pm.duration, pm.drug_name)
            # Try to match pharmacy item by name (case-insensitive)
            # Stage 1: inventory name contains prescription name (or exact match)
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
            # Stage 2: prescription name contains inventory name
            # e.g. drug_name="Tab Ultracet" while inventory is stored as "Ultracet"
            if not item:
                drug_lower = drug_name_clean.lower()
                for candidate in PharmacyItem.objects.filter(clinic=clinic).select_related('medicine').prefetch_related('batches'):
                    inv_name = (candidate.medicine.name if candidate.medicine else candidate.custom_name or '').lower()
                    if inv_name and inv_name in drug_lower:
                        item = candidate
                        break
            batch = item.use_first_batch if item else None
            # Use total_quantity across ALL batches so multi-batch dispensing shows correct stock
            total_qty = item.total_quantity if item else 0
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
                'stock_qty': total_qty,
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

    # Layer 2: warn about any matched medicines whose first batch has price=0
    zero_price_names = [
        row['drug_name'] for row in medicine_rows
        if row['item_id'] and row['unit_price'] == '0'
    ]

    return render(request, 'pharmacy/dispense.html', {
        'visit': visit,
        'patient': visit.patient,
        'clinic': clinic,
        'existing_rx': existing_rx,
        'medicine_rows': medicine_rows,
        'all_items': all_items,
        'already_billed': already_billed,
        'zero_price_names': zero_price_names,
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

    from django.db.models import Sum

    # Validate all items before writing anything — check stock and price
    for item_data in items_data:
        batch_id = item_data.get('batch_id')
        qty = int(item_data.get('qty', 0) or 0)
        if not batch_id or qty <= 0:
            return JsonResponse({'ok': False, 'error': 'Invalid item data.'}, status=400)
        batch = get_object_or_404(PharmacyBatch, pk=batch_id, item__clinic=clinic)
        pharmacy_item = batch.item
        total_available = pharmacy_item.batches.filter(quantity__gt=0).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        if total_available < qty:
            return JsonResponse({
                'ok': False,
                'error': (
                    f'Not enough total stock for {pharmacy_item.display_name}. '
                    f'Total available across all batches: {total_available}'
                )
            }, status=400)
        # Layer 2: block dispense if the billing batch (first FEFO batch) has price=0
        first_fefo = (
            pharmacy_item.batches.filter(quantity__gt=0).order_by('expiry_date').first()
        )
        billing_price_check = first_fefo.unit_price if first_fefo else decimal.Decimal('0')
        if billing_price_check <= 0:
            return JsonResponse({
                'ok': False,
                'error': (
                    f'Cannot dispense {pharmacy_item.display_name} — MRP is ₹0. '
                    f'Please go to Pharmacy → Edit Batch and set the correct price first.'
                )
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

            # Load the preferred (first) batch to identify the PharmacyItem
            first_batch = PharmacyBatch.objects.select_for_update().get(pk=batch_id)
            pharmacy_item = first_batch.item
            # Use the first (FEFO) batch's price for ALL splits of this medicine.
            # Overflow batches may have unit_price=0 if added without a price — using
            # their individual price would silently under-bill patients.
            billing_price = first_batch.unit_price

            # FEFO multi-batch: get all batches with stock in expiry order, lock them
            fefo_batches = list(
                PharmacyBatch.objects
                .select_for_update()
                .filter(item=pharmacy_item, quantity__gt=0)
                .order_by('expiry_date')
            )

            remaining = qty
            for batch in fefo_batches:
                if remaining <= 0:
                    break
                use = min(batch.quantity, remaining)

                batch.quantity -= use
                batch.save(update_fields=['quantity', 'updated_at'])

                DispensedItem.objects.create(
                    visit=visit,
                    prescription_med_id=prescription_med_id or None,
                    pharmacy_item=pharmacy_item,
                    batch=batch,
                    quantity_dispensed=use,
                    unit_price=billing_price,  # always use first batch's price
                    is_substitute=is_substitute,
                    notes=notes,
                    dispensed_by=request.user.staff_profile,
                )
                subtotal += billing_price * use
                remaining -= use

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
    import urllib.parse
    clinic = _get_clinic(request)
    bill = get_object_or_404(PharmacyBill, pk=bill_id, clinic=clinic)
    dispensed_items = bill.visit.dispensed_items.select_related(
        'pharmacy_item', 'pharmacy_item__medicine', 'batch'
    ).all()
    # Pre-calculate line amounts (avoids widthratio integer truncation in template)
    dispensed_items = list(dispensed_items)
    for item in dispensed_items:
        item.line_amount = item.quantity_dispensed * item.unit_price
    prescription = getattr(bill.visit, 'prescription', None)
    discount_amount = bill.subtotal - bill.final_amount

    # WhatsApp deeplink for patient (if phone available)
    wa_url = ''
    phone = bill.visit.patient.phone
    if phone:
        msg = (
            f"Dear patient, your medicine bill from {clinic.name} is ready.\n"
            f"Bill No: {bill.bill_number} | Total: Rs {bill.final_amount}\n"
            f"Please save the PDF sent to you for your records."
        )
        wa_url = f"https://wa.me/91{phone}?text={urllib.parse.quote(msg)}"

    return render(request, 'pharmacy/bill.html', {
        'bill': bill,
        'visit': bill.visit,
        'patient': bill.visit.patient,
        'clinic': clinic,
        'dispensed_items': dispensed_items,
        'prescription': prescription,
        'discount_amount': discount_amount,
        'wa_url': wa_url,
    })


@require_permission('can_dispense_bill')
@require_POST
def pharmacy_settings_view(request):
    """POST. Save clinic-level pharmacy settings (default discount %)."""
    from django.contrib import messages
    clinic = _get_clinic(request)
    try:
        disc = int(request.POST.get('default_discount', 0))
        clinic.default_medicine_discount = max(0, min(100, disc))
        clinic.save(update_fields=['default_medicine_discount'])
        messages.success(request, f'Default discount set to {clinic.default_medicine_discount}%.')
    except (ValueError, TypeError):
        messages.error(request, 'Invalid discount value.')
    return redirect('pharmacy:dashboard')


# ---------------------------------------------------------------------------
# Item detail API
# ---------------------------------------------------------------------------

@require_permission('can_dispense_bill')
@require_GET
def item_detail_api(request):
    """GET JSON. Returns item + FEFO batch info for use in dispense manual-add."""
    clinic = _get_clinic(request)
    item_id = request.GET.get('id')
    item = get_object_or_404(PharmacyItem, pk=item_id, clinic=clinic)
    batch = item.use_first_batch
    return JsonResponse({
        'id': item.pk,
        'name': item.display_name,
        'batch_id': batch.pk if batch else None,
        'unit_price': str(batch.unit_price) if batch else '0',
        'stock_qty': batch.quantity if batch else 0,
        'in_stock': item.in_stock,
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


# ---------------------------------------------------------------------------
# Walk-in dispense
# ---------------------------------------------------------------------------

@require_permission('can_dispense_bill')
def walk_in_view(request):
    """Direct walk-in dispense — search/register patient then go straight to dispense."""
    from reception.models import Patient, Visit
    from django.utils import timezone as tz

    clinic = _get_clinic(request)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'select':
            patient_id = request.POST.get('patient_id', '')
            patient = get_object_or_404(Patient, pk=patient_id, clinic=clinic)
        elif action == 'register':
            full_name = request.POST.get('full_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            if not full_name or not phone:
                from django.contrib import messages as _messages
                _messages.error(request, 'Name and phone are required.')
                return render(request, 'pharmacy/walk_in.html', {'clinic': clinic})
            try:
                age_val = int(request.POST.get('age') or 0) or None
            except (ValueError, TypeError):
                age_val = None
            patient, _ = Patient.objects.get_or_create(
                phone=phone, clinic=clinic,
                defaults={
                    'full_name': full_name,
                    'age': age_val,
                    'gender': request.POST.get('gender', 'M'),
                }
            )
        else:
            return redirect('pharmacy:walk_in')

        # Find today's visit or create one
        today = tz.now().date()
        visit = Visit.objects.filter(patient=patient, clinic=clinic, visit_date=today).first()
        if not visit:
            last = Visit.objects.filter(clinic=clinic, visit_date=today).order_by('-token_number').first()
            token = (last.token_number + 1) if last else 1
            visit = Visit.objects.create(
                patient=patient, clinic=clinic,
                visit_date=today, token_number=token,
                status='done',
            )
        return redirect('pharmacy:dispense', visit_id=visit.id)

    return render(request, 'pharmacy/walk_in.html', {'clinic': clinic})


# ---------------------------------------------------------------------------
# Edit / Re-dispense bill
# ---------------------------------------------------------------------------

@require_permission('can_dispense_bill')
def medicine_return_view(request, bill_id=None):
    """Show return form. GET with bill_id pre-loads the bill."""
    clinic = _get_clinic(request)
    bill = None
    dispensed_items = []
    error = None

    if request.method == 'POST' and not bill_id:
        # Step 1: lookup bill by number
        bill_number = request.POST.get('bill_number', '').strip()
        try:
            bill = PharmacyBill.objects.get(bill_number=bill_number, clinic=clinic)
            return redirect('pharmacy:return_bill', bill_id=bill.pk)
        except PharmacyBill.DoesNotExist:
            error = f'Bill number "{bill_number}" not found.'

    if bill_id:
        bill = get_object_or_404(PharmacyBill, pk=bill_id, clinic=clinic)
        dispensed_items = bill.visit.dispensed_items.select_related(
            'pharmacy_item', 'batch'
        ).all()
        # annotate with line_amount
        dispensed_items = list(dispensed_items)
        for item in dispensed_items:
            item.line_amount = item.quantity_dispensed * item.unit_price

    return render(request, 'pharmacy/return.html', {
        'clinic': clinic,
        'bill': bill,
        'dispensed_items': dispensed_items,
        'error': error,
    })


@require_permission('can_dispense_bill')
@require_POST
def process_return_view(request, bill_id):
    """Process the medicine return: restore inventory, record return."""
    import json as _json
    clinic = _get_clinic(request)
    bill = get_object_or_404(PharmacyBill, pk=bill_id, clinic=clinic)

    try:
        data = _json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid request.'}, status=400)

    returns = data.get('returns', [])  # [{dispensed_item_id, return_qty}, ...]
    if not returns:
        return JsonResponse({'ok': False, 'error': 'No items to return.'}, status=400)

    with transaction.atomic():
        total_returned = decimal.Decimal('0.00')
        processed = 0
        for r in returns:
            di_id = r.get('dispensed_item_id')
            return_qty = int(r.get('return_qty', 0) or 0)
            if return_qty <= 0:
                continue
            di = get_object_or_404(DispensedItem, pk=di_id, visit=bill.visit)
            if return_qty > di.quantity_dispensed:
                return JsonResponse({
                    'ok': False,
                    'error': f'Cannot return more than dispensed for {di.pharmacy_item.display_name}.'
                }, status=400)
            # Restore inventory
            batch = PharmacyBatch.objects.select_for_update().get(pk=di.batch_id)
            batch.quantity += return_qty
            batch.save(update_fields=['quantity', 'updated_at'])
            # Record the return on the dispensed item
            di.quantity_returned = (di.quantity_returned or 0) + return_qty
            di.save(update_fields=['quantity_returned'])
            total_returned += di.unit_price * return_qty
            processed += 1

    if processed == 0:
        return JsonResponse({'ok': False, 'error': 'No items to return.'}, status=400)

    return JsonResponse({
        'ok': True,
        'total_returned': str(total_returned),
        'redirect': f'/pharmacy/bill/{bill.pk}/',
    })


@require_permission('can_dispense_bill')
@require_POST
def edit_bill_view(request, bill_id):
    """POST. Reverse a bill — restore stock and delete bill so dispense can redo."""
    clinic = _get_clinic(request)
    bill = get_object_or_404(PharmacyBill, pk=bill_id, clinic=clinic)
    visit = bill.visit
    with transaction.atomic():
        for di in visit.dispensed_items.select_related('batch').all():
            di.batch.quantity += di.quantity_dispensed
            di.batch.save(update_fields=['quantity'])
        visit.dispensed_items.all().delete()
        bill.delete()
    from django.contrib import messages as _messages
    _messages.success(request, 'Bill reversed. Please re-dispense.')
    return redirect('pharmacy:dispense', visit_id=visit.id)


# ---------------------------------------------------------------------------
# Bill history
# ---------------------------------------------------------------------------

@require_permission('can_dispense_bill')
def bill_list_view(request):
    """List all bills for the clinic with date/search filtering."""
    clinic = _get_clinic(request)
    from django.utils import timezone as tz
    from django.db.models import Sum, Count
    import datetime

    range_param = request.GET.get('range', '30')
    try:
        days = int(range_param)
        if days not in (7, 30, 90, 365):
            days = 30
    except ValueError:
        days = 30
    today = tz.now().date()
    since = today - datetime.timedelta(days=days - 1)

    bills_qs = (
        PharmacyBill.objects
        .filter(clinic=clinic, created_at__date__gte=since)
        .select_related('visit__patient', 'created_by')
        .order_by('-created_at')
    )

    # Optional search by patient name or bill number
    search = request.GET.get('q', '').strip()
    if search:
        bills_qs = bills_qs.filter(
            visit__patient__full_name__icontains=search
        ) | PharmacyBill.objects.filter(
            clinic=clinic, created_at__date__gte=since,
            bill_number__icontains=search
        ).select_related('visit__patient', 'created_by').order_by('-created_at')

    total_revenue = bills_qs.aggregate(t=Sum('final_amount'))['t'] or 0

    return render(request, 'pharmacy/bill_list.html', {
        'clinic': clinic,
        'bills': bills_qs,
        'days': days,
        'since': since,
        'today': today,
        'search': search,
        'range_choices': [(7, '7 Days'), (30, '30 Days'), (90, '3 Months'), (365, '1 Year')],
        'total_revenue': total_revenue,
        'total_bills': bills_qs.count(),
    })


# ---------------------------------------------------------------------------
# Inventory analytics
# ---------------------------------------------------------------------------

@require_permission('can_view_analytics')
def pharmacy_analytics_view(request):
    """Pharmacy analytics: dispensing history, top medicines, returns, revenue."""
    clinic = _get_clinic(request)
    from django.utils import timezone as tz
    from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField
    from django.db.models.functions import TruncDate
    import datetime
    import json as _json

    range_param = request.GET.get('range', '30')
    try:
        days = int(range_param)
        if days not in (7, 30, 90, 365):
            days = 30
    except ValueError:
        days = 30
    today = tz.now().date()
    since = today - datetime.timedelta(days=days - 1)

    # Revenue by day for chart
    daily_revenue = (
        PharmacyBill.objects
        .filter(clinic=clinic, created_at__date__gte=since)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum('final_amount'), bill_count=Count('id'))
        .order_by('day')
    )
    daily_map = {r['day']: {'total': float(r['total'] or 0), 'count': r['bill_count']}
                 for r in daily_revenue}
    chart_labels = []
    chart_revenue = []
    chart_bills = []
    for i in range(days):
        d = since + datetime.timedelta(days=i)
        chart_labels.append(d.strftime('%d %b'))
        chart_revenue.append(daily_map.get(d, {}).get('total', 0))
        chart_bills.append(daily_map.get(d, {}).get('count', 0))

    # Top dispensed medicines by quantity
    top_medicines_qs = (
        DispensedItem.objects
        .filter(visit__clinic=clinic, dispensed_at__date__gte=since)
        .values('pharmacy_item__medicine__name', 'pharmacy_item__custom_name')
        .annotate(
            total_qty=Sum('quantity_dispensed'),
            total_rev=Sum(ExpressionWrapper(
                F('quantity_dispensed') * F('unit_price'),
                output_field=DecimalField()
            ))
        )
        .order_by('-total_qty')[:15]
    )
    top_meds_list = []
    for row in top_medicines_qs:
        name = row['pharmacy_item__medicine__name'] or row['pharmacy_item__custom_name'] or 'Unknown'
        top_meds_list.append({
            'name': name,
            'qty': row['total_qty'],
            'rev': float(row['total_rev'] or 0),
        })

    # Recent returns
    returns_qs = (
        DispensedItem.objects
        .filter(visit__clinic=clinic, dispensed_at__date__gte=since, quantity_returned__gt=0)
        .select_related('pharmacy_item__medicine', 'visit__patient')
        .order_by('-dispensed_at')[:50]
    )

    # Summary totals
    total_revenue = PharmacyBill.objects.filter(
        clinic=clinic, created_at__date__gte=since
    ).aggregate(t=Sum('final_amount'))['t'] or 0

    total_bills = PharmacyBill.objects.filter(
        clinic=clinic, created_at__date__gte=since
    ).count()

    total_items_dispensed = DispensedItem.objects.filter(
        visit__clinic=clinic, dispensed_at__date__gte=since
    ).aggregate(t=Sum('quantity_dispensed'))['t'] or 0

    total_returned = DispensedItem.objects.filter(
        visit__clinic=clinic, dispensed_at__date__gte=since
    ).aggregate(t=Sum('quantity_returned'))['t'] or 0

    return render(request, 'pharmacy/analytics.html', {
        'clinic': clinic,
        'days': days,
        'since': since,
        'today': today,
        'range_choices': [(7, '7 Days'), (30, '30 Days'), (90, '3 Months'), (365, '1 Year')],
        'chart_labels': _json.dumps(chart_labels),
        'chart_revenue': _json.dumps(chart_revenue),
        'chart_bills': _json.dumps(chart_bills),
        'top_meds_list': top_meds_list,
        'returns_qs': returns_qs,
        'total_revenue': total_revenue,
        'total_bills': total_bills,
        'total_items_dispensed': total_items_dispensed,
        'total_returned': total_returned,
    })
