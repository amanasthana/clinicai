import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0011_merge_duplicate_batches'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='pharmacybatch',
            constraint=models.UniqueConstraint(
                models.F('item'), django.db.models.functions.text.Lower('batch_number'),
                condition=models.Q(('batch_number', ''), _negated=True),
                name='pharmacy_batch_number_unique_per_item',
            ),
        ),
    ]
