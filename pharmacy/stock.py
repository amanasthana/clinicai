"""
Stock rules shared by the pharmacy views.

- One batch number appears only once per medicine. Adding stock with a batch number
  that already exists tops up that batch instead of creating a second row.
- Medicines and batches that were sold can't be hard-deleted (bills point at them).
  Removing them archives them instead: stock goes to 0 and they disappear from
  inventory, while old bills keep working.
- Scanned / typed names are matched to existing medicines ignoring case, spacing,
  punctuation and spelling of the form ("TAB DOLO-650" == "Dolo 650 Tablet").
- User input is validated here so bad values show a message instead of a 500.
"""
import datetime
import decimal
import re

from django.db import IntegrityError, transaction

from .models import DispensedItem, PharmacyBatch, PharmacyItem, StockReceipt


class StockInputError(ValueError):
    """Bad user input. The message is safe to show to the user."""


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

MAX_PRICE = decimal.Decimal('99999999.99')   # DecimalField(max_digits=10, decimal_places=2)
MAX_QTY = 2_147_483_647                      # PositiveIntegerField upper bound


def _to_decimal(raw, label):
    text = str(raw if raw is not None else '').strip()
    text = text.replace(',', '').replace('₹', '').replace('Rs', '').replace('rs', '').strip()
    if not text:
        return decimal.Decimal('0')
    try:
        value = decimal.Decimal(text)
    except decimal.InvalidOperation:
        raise StockInputError(f'{label} must be a number.')
    if not value.is_finite():
        raise StockInputError(f'{label} must be a number.')
    return value


def parse_quantity(raw, label='Quantity'):
    value = _to_decimal(raw, label)
    if value < 0:
        raise StockInputError(f'{label} cannot be negative.')
    if value != value.to_integral_value():
        raise StockInputError(f'{label} must be a whole number.')
    if value > MAX_QTY:
        raise StockInputError(f'{label} is too large.')
    return int(value)


def parse_price(raw, label='Price'):
    value = _to_decimal(raw, label)
    if value < 0:
        raise StockInputError(f'{label} cannot be negative.')
    if value > MAX_PRICE:
        raise StockInputError(f'{label} is too large.')
    return value.quantize(decimal.Decimal('0.01'), rounding=decimal.ROUND_HALF_UP)


def parse_gst(raw, label='GST %'):
    value = _to_decimal(raw, label)
    if value < 0 or value > 100:
        raise StockInputError(f'{label} must be between 0 and 100.')
    return value.quantize(decimal.Decimal('0.01'), rounding=decimal.ROUND_HALF_UP)


_EXPIRY_FULL = ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y')
_EXPIRY_MONTH = ('%Y-%m', '%m/%Y', '%m-%Y', '%m.%Y', '%m/%y', '%m-%y', '%b-%Y', '%b %Y', '%b-%y', '%b %y')


def parse_expiry(raw):
    """Accepts a full date or a month (03/2027, 2027-03, Mar-27). Months map to day 1."""
    text = str(raw or '').strip()
    if not text:
        return None
    for fmt in _EXPIRY_FULL:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    for fmt in _EXPIRY_MONTH:
        try:
            return datetime.datetime.strptime(text, fmt).date().replace(day=1)
        except ValueError:
            pass
    raise StockInputError(f'Expiry "{text}" is not a valid date. Use a format like 2027-03 or 03/2027.')


def parse_text(raw, max_len, label):
    text = str(raw or '').strip()
    if len(text) > max_len:
        raise StockInputError(f'{label} is too long (max {max_len} characters).')
    return text


def clean_batch_number(raw):
    return parse_text(raw, 50, 'Batch number')


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

_FORM_WORDS = {
    'tab': 'tab', 'tabs': 'tab', 'tablet': 'tab', 'tablets': 'tab', 'tb': 'tab',
    'cap': 'cap', 'caps': 'cap', 'capsule': 'cap', 'capsules': 'cap',
    'syp': 'syrup', 'syr': 'syrup', 'syrup': 'syrup',
    'inj': 'inj', 'injection': 'inj',
    'susp': 'susp', 'suspension': 'susp',
    'oint': 'oint', 'ointment': 'oint',
    'cream': 'cream', 'crm': 'cream',
    'gel': 'gel', 'lotion': 'lotion',
    'drop': 'drops', 'drops': 'drops',
    'sol': 'soln', 'soln': 'soln', 'solution': 'soln',
    'sachet': 'sachet', 'spray': 'spray', 'inhaler': 'inhaler', 'powder': 'powder',
}


def name_key(name, form=''):
    """(name tokens, form set). Strength units like 'mg' are dropped: 'Pan 40mg' == 'Pan 40'."""
    text = f'{name or ""} {form or ""}'.lower()
    text = re.sub(r'(\d)([a-z])', r'\1 \2', text)
    text = re.sub(r'([a-z])(\d)', r'\1 \2', text)
    tokens = re.findall(r'[a-z0-9]+', text)
    forms, rest = set(), []
    for tok in tokens:
        if tok in _FORM_WORDS:
            forms.add(_FORM_WORDS[tok])
        elif tok != 'mg':
            rest.append(tok)
    return tuple(rest), frozenset(forms)


def keys_match(a, b):
    """Same name, and either the same form or one side doesn't say.
    'Calpol Tab' and 'Calpol Syrup' never match."""
    if not a[0] or a[0] != b[0]:
        return False
    return not a[1] or not b[1] or a[1] == b[1]


def item_key(item):
    if item.medicine_id:
        return name_key(item.medicine.name, item.medicine.form)
    return name_key(item.custom_name)


def find_matching_item(clinic, medicine=None, custom_name=''):
    """Existing medicine in this clinic (archived ones included, so they come back)."""
    items = PharmacyItem.all_objects.filter(clinic=clinic).select_related('medicine').order_by('is_archived', 'pk')
    if medicine is not None:
        same = items.filter(medicine=medicine).first()
        if same:
            return same
        key = name_key(medicine.name, medicine.form)
        candidates = items.filter(medicine__isnull=True)
    else:
        key = name_key(custom_name)
        candidates = items
    # Exact name AND form only. "Dolo 650" (no form) is never put on "Dolo 650 Syrup"
    # automatically — near-matches show up as merge suggestions on the dashboard instead.
    for cand in candidates:
        if item_key(cand) == key:
            return cand
    return None


def duplicate_groups(items):
    """Groups of active medicines that look like the same product."""
    buckets = {}
    for item in items:
        key = item_key(item)
        if key[0]:
            buckets.setdefault(key[0], []).append((key, item))
    groups = []
    for entries in buckets.values():
        if len(entries) < 2:
            continue
        used = set()
        for i, (ki, a) in enumerate(entries):
            if a.pk in used:
                continue
            group = [a]
            for kj, b in entries[i + 1:]:
                if b.pk not in used and keys_match(ki, kj):
                    group.append(b)
            if len(group) > 1:
                used.update(x.pk for x in group)
                groups.append(group)
    return groups


# ---------------------------------------------------------------------------
# Adding stock
# ---------------------------------------------------------------------------

def _unarchive_item(item):
    if item.is_archived:
        item.is_archived = False
        item.save(update_fields=['is_archived', 'updated_at'])


def add_stock(item, batch_number, expiry_date, quantity, unit_price,
              purchase_price=decimal.Decimal('0'), purchase_gst_percent=decimal.Decimal('0'),
              added_by=None):
    """Add stock to a medicine. Returns (batch, merged). merged=True means an existing
    batch with the same number was topped up. Every call records a dated StockReceipt,
    so parts of one batch received on different days keep their own dates."""
    batch_number = (batch_number or '').strip()
    for attempt in range(2):
        try:
            with transaction.atomic():
                item = PharmacyItem.all_objects.select_for_update().get(pk=item.pk)
                existing = None
                if batch_number:
                    existing = (
                        PharmacyBatch.all_objects.select_for_update()
                        .filter(item=item, batch_number__iexact=batch_number)
                        .order_by('pk').first()
                    )
                if existing:
                    existing.quantity += quantity
                    existing.is_archived = False
                    if expiry_date:
                        existing.expiry_date = expiry_date
                    if unit_price > 0:
                        existing.unit_price = unit_price
                    if purchase_price > 0:
                        existing.purchase_price = purchase_price
                    if purchase_gst_percent > 0:
                        existing.purchase_gst_percent = purchase_gst_percent
                    existing.save()
                    batch, merged = existing, True
                else:
                    batch = PharmacyBatch.all_objects.create(
                        item=item,
                        batch_number=batch_number,
                        expiry_date=expiry_date,
                        quantity=quantity,
                        unit_price=unit_price,
                        purchase_price=purchase_price,
                        purchase_gst_percent=purchase_gst_percent,
                    )
                    merged = False
                if quantity > 0:
                    StockReceipt.objects.create(
                        batch=batch, quantity=quantity,
                        unit_price=unit_price if unit_price > 0 else batch.unit_price,
                        purchase_price=purchase_price if purchase_price > 0 else batch.purchase_price,
                        purchase_gst_percent=(purchase_gst_percent if purchase_gst_percent > 0
                                              else batch.purchase_gst_percent),
                        added_by=added_by,
                    )
                _unarchive_item(item)
                return batch, merged
        except IntegrityError:
            # Another request created the same batch number at the same moment — retry as a top-up
            if attempt:
                raise
    raise RuntimeError('unreachable')


def batch_number_taken(item, batch_number, exclude_pk=None):
    if not batch_number:
        return None
    qs = PharmacyBatch.all_objects.filter(item=item, batch_number__iexact=batch_number)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


# ---------------------------------------------------------------------------
# Removing stock
# ---------------------------------------------------------------------------

def remove_batch(batch):
    """Delete a batch, or archive it if it was ever sold. Returns 'deleted' or 'archived'."""
    if DispensedItem.objects.filter(batch_id=batch.pk).exists():
        batch.is_archived = True
        batch.quantity = 0
        batch.save(update_fields=['is_archived', 'quantity', 'updated_at'])
        return 'archived'
    batch.delete()
    return 'deleted'


def remove_item(item):
    """Delete a medicine, or archive it (and its batches) if any of it was ever sold."""
    with transaction.atomic():
        for batch in PharmacyBatch.all_objects.filter(item=item):
            remove_batch(batch)
        sold = DispensedItem.objects.filter(pharmacy_item_id=item.pk).exists()
        if not sold and not PharmacyBatch.all_objects.filter(item=item).exists():
            item.delete()
            return 'deleted'
        item.is_archived = True
        item.reorder_flagged = False
        item.save(update_fields=['is_archived', 'reorder_flagged', 'updated_at'])
        return 'archived'


def restore_returned_stock(batch_id, qty):
    """Put returned units back. Brings an archived batch/medicine back into inventory."""
    batch = PharmacyBatch.all_objects.select_for_update().select_related('item').get(pk=batch_id)
    batch.quantity += qty
    batch.is_archived = False
    batch.save(update_fields=['quantity', 'is_archived', 'updated_at'])
    _unarchive_item(batch.item)
    return batch


# ---------------------------------------------------------------------------
# Merging duplicate medicines
# ---------------------------------------------------------------------------

def merge_items(source, target):
    """Move everything from `source` into `target` and delete `source`.
    Batches with the same number are combined. Sales history moves with them."""
    if source.pk == target.pk or source.clinic_id != target.clinic_id:
        raise StockInputError('Pick a different medicine from the same clinic.')
    with transaction.atomic():
        source = PharmacyItem.all_objects.select_for_update().get(pk=source.pk)
        target = PharmacyItem.all_objects.select_for_update().get(pk=target.pk)
        moved_active = False
        for b in PharmacyBatch.all_objects.select_for_update().filter(item=source).order_by('pk'):
            if not b.is_archived:
                moved_active = True
            match = batch_number_taken(target, b.batch_number.strip())
            if match:
                match.quantity += b.quantity
                if b.quantity > 0 or not b.is_archived:
                    match.is_archived = False
                if not match.expiry_date and b.expiry_date:
                    match.expiry_date = b.expiry_date
                if match.unit_price <= 0 < b.unit_price:
                    match.unit_price = b.unit_price
                if match.purchase_price <= 0 < b.purchase_price:
                    match.purchase_price = b.purchase_price
                match.save()
                DispensedItem.objects.filter(batch_id=b.pk).update(batch=match)
                StockReceipt.objects.filter(batch_id=b.pk).update(batch=match)
                b.delete()
            else:
                b.item = target
                b.save(update_fields=['item', 'updated_at'])
        DispensedItem.objects.filter(pharmacy_item_id=source.pk).update(pharmacy_item=target)

        fields = []
        if moved_active and target.is_archived:
            target.is_archived = False
            fields.append('is_archived')
        if not target.medicine_id and not target.custom_generic_name and source.display_generic:
            target.custom_generic_name = source.display_generic[:250]
            fields.append('custom_generic_name')
        if source.reorder_flagged and not target.reorder_flagged:
            target.reorder_flagged = True
            fields.append('reorder_flagged')
        if fields:
            target.save(update_fields=fields + ['updated_at'])
        source.delete()
    return target
