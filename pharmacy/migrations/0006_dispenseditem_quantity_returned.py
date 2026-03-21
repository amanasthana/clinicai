from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('pharmacy', '0005_add_dispensed_and_bill'),
    ]
    operations = [
        migrations.AddField(
            model_name='dispenseditem',
            name='quantity_returned',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
