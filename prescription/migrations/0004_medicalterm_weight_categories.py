from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prescription', '0003_add_medical_terms'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicalterm',
            name='weight',
            field=models.PositiveSmallIntegerField(
                default=50,
                help_text='Higher = surfaces first. Common terms get 90-100, rare ones 10-20.'
            ),
        ),
        migrations.AlterField(
            model_name='medicalterm',
            name='category',
            field=models.CharField(
                choices=[
                    ('symptom', 'Symptom'),
                    ('diagnosis', 'Diagnosis'),
                    ('investigation', 'Investigation'),
                    ('procedure', 'Procedure'),
                    ('medicine', 'Medicine'),
                    ('advice', 'Advice'),
                    ('snippet', 'Snippet'),
                    ('abbreviation', 'Abbreviation'),
                ],
                max_length=20,
            ),
        ),
    ]
