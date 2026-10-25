"""Give every existing batch one stock entry on its original received date.

Quantity = what's in stock now + what was sold − what was returned, i.e. roughly what
came in. Earlier top-ups of the same batch can't be separated any more, so they are
part of this first entry.
"""
from django.db import migrations
from django.db.models import Sum


def backfill(apps, schema_editor):
    PharmacyBatch = apps.get_model('pharmacy', 'PharmacyBatch')
    DispensedItem = apps.get_model('pharmacy', 'DispensedItem')
    StockReceipt = apps.get_model('pharmacy', 'StockReceipt')

    sold = {
        row['batch_id']: (row['out'] or 0) - (row['back'] or 0)
        for row in DispensedItem.objects.values('batch_id')
        .annotate(out=Sum('quantity_dispensed'), back=Sum('quantity_returned'))
    }
    has_receipt = set(StockReceipt.objects.values_list('batch_id', flat=True))
    new = []
    for b in PharmacyBatch.objects.all().iterator():
        if b.pk in has_receipt:
            continue
        qty = b.quantity + max(sold.get(b.pk, 0), 0)
        if qty <= 0:
            continue
        new.append(StockReceipt(
            batch_id=b.pk, quantity=qty, received_date=b.received_date,
            unit_price=b.unit_price, purchase_price=b.purchase_price,
            purchase_gst_percent=b.purchase_gst_percent,
        ))
    StockReceipt.objects.bulk_create(new, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0013_stock_receipts'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
