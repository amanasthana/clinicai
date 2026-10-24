"""Combine batches that share a batch number within the same medicine.

Before this, re-saving a scanned bill or double-tapping "Save" created the same batch
twice, so a sale could be split across two rows and appear twice on the bill.
The oldest row is kept; quantities are added up and sales are re-pointed to it.
"""
from django.db import migrations


def merge_duplicates(apps, schema_editor):
    PharmacyBatch = apps.get_model('pharmacy', 'PharmacyBatch')
    DispensedItem = apps.get_model('pharmacy', 'DispensedItem')

    # Trim stray spaces so " B001" and "B001" count as the same batch
    for b in PharmacyBatch.objects.exclude(batch_number='').only('pk', 'batch_number'):
        clean = b.batch_number.strip()
        if clean != b.batch_number:
            PharmacyBatch.objects.filter(pk=b.pk).update(batch_number=clean)

    groups = {}
    for b in PharmacyBatch.objects.exclude(batch_number='').order_by('pk'):
        groups.setdefault((b.item_id, b.batch_number.lower()), []).append(b)

    for batches in groups.values():
        if len(batches) < 2:
            continue
        keep, extras = batches[0], batches[1:]
        newest_first = sorted(batches, key=lambda x: x.pk, reverse=True)
        keep.quantity = sum(b.quantity for b in batches)
        keep.is_archived = all(b.is_archived for b in batches)
        if not keep.expiry_date:
            keep.expiry_date = next((b.expiry_date for b in batches if b.expiry_date), None)
        # Latest non-zero prices win (MRP may have been corrected on the newer row)
        keep.unit_price = next((b.unit_price for b in newest_first if b.unit_price > 0), keep.unit_price)
        keep.purchase_price = next((b.purchase_price for b in newest_first if b.purchase_price > 0), keep.purchase_price)
        keep.purchase_gst_percent = next(
            (b.purchase_gst_percent for b in newest_first if b.purchase_gst_percent > 0), keep.purchase_gst_percent)
        keep.save()
        extra_ids = [b.pk for b in extras]
        DispensedItem.objects.filter(batch_id__in=extra_ids).update(batch_id=keep.pk)
        PharmacyBatch.objects.filter(pk__in=extra_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0010_archive_flags'),
    ]

    operations = [
        migrations.RunPython(merge_duplicates, migrations.RunPython.noop),
    ]
