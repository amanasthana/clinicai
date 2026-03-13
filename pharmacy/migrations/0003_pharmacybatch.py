"""
Migration: introduce PharmacyBatch model and convert PharmacyItem to medicine master.

Schema changes:
  - Create PharmacyBatch
  - Remove batch_number, expiry_date, quantity, unit_price from PharmacyItem

Data migration:
  - For each existing PharmacyItem, create one PharmacyBatch with its data.
  - Deduplicate PharmacyItems that share the same clinic+medicine:
      merge all duplicate rows into the first one, move their batches across,
      then delete the duplicates.
"""

import django.db.models.deletion
from django.db import migrations, models


def migrate_items_to_batches(apps, schema_editor):
    PharmacyItem = apps.get_model('pharmacy', 'PharmacyItem')
    PharmacyBatch = apps.get_model('pharmacy', 'PharmacyBatch')

    # Step 1: For every existing item create a PharmacyBatch with the old fields.
    for item in PharmacyItem.objects.all():
        PharmacyBatch.objects.create(
            item=item,
            batch_number=item.batch_number or '',
            expiry_date=item.expiry_date,
            quantity=item.quantity,
            unit_price=item.unit_price,
        )

    # Step 2: Deduplicate rows that share clinic + medicine (non-null medicine).
    from django.db.models import Count
    dupes = (
        PharmacyItem.objects
        .exclude(medicine__isnull=True)
        .values('clinic', 'medicine')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )
    for group in dupes:
        rows = list(
            PharmacyItem.objects.filter(
                clinic_id=group['clinic'],
                medicine_id=group['medicine'],
            ).order_by('id')
        )
        # Keep the first row as master, reassign batches from duplicates and delete them.
        master = rows[0]
        for dup in rows[1:]:
            PharmacyBatch.objects.filter(item=dup).update(item=master)
            dup.delete()


def reverse_migrate(apps, schema_editor):
    """
    Best-effort reversal: for each PharmacyItem take the first batch's data and
    put it back into the item's old fields. Remaining batches are lost.
    """
    PharmacyItem = apps.get_model('pharmacy', 'PharmacyItem')
    PharmacyBatch = apps.get_model('pharmacy', 'PharmacyBatch')

    for item in PharmacyItem.objects.all():
        first_batch = PharmacyBatch.objects.filter(item=item).order_by('id').first()
        if first_batch:
            item.batch_number = first_batch.batch_number or ''
            item.expiry_date = first_batch.expiry_date
            item.quantity = first_batch.quantity
            item.unit_price = first_batch.unit_price
            item.save()


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0002_replace_with_catalog_and_favorites'),
    ]

    operations = [
        # 1. Create PharmacyBatch table (referencing PharmacyItem which already exists)
        migrations.CreateModel(
            name='PharmacyBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='batches',
                    to='pharmacy.pharmacyitem',
                )),
                ('batch_number', models.CharField(blank=True, max_length=50)),
                ('expiry_date', models.DateField(blank=True, null=True)),
                ('quantity', models.PositiveIntegerField(default=0)),
                ('unit_price', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('received_date', models.DateField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['expiry_date'],
            },
        ),

        # 2. Copy existing PharmacyItem batch data → PharmacyBatch rows
        migrations.RunPython(migrate_items_to_batches, reverse_migrate),

        # 3. Remove the now-redundant fields from PharmacyItem
        migrations.RemoveField(model_name='pharmacyitem', name='batch_number'),
        migrations.RemoveField(model_name='pharmacyitem', name='expiry_date'),
        migrations.RemoveField(model_name='pharmacyitem', name='quantity'),
        migrations.RemoveField(model_name='pharmacyitem', name='unit_price'),
    ]
