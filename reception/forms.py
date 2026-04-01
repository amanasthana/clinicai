from django import forms
from .models import Patient, Visit


class PatientForm(forms.ModelForm):
    """Register a new patient or update an existing one."""
    chief_complaint = forms.CharField(
        max_length=300,
        required=False,
        label='Chief Complaint (reason for visit today)',
        widget=forms.TextInput(attrs={
            'class': 'input-field',
            'placeholder': 'e.g. fever, stomach pain, follow-up...',
        }),
    )

    class Meta:
        model = Patient
        fields = ['full_name', 'guardian_name', 'phone', 'age', 'gender', 'address', 'blood_group', 'allergies', 'notes']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Patient full name'}),
            'guardian_name': forms.TextInput(attrs={'class': 'input-field', 'placeholder': "Husband's / Father's name (optional)"}),
            'phone': forms.TextInput(attrs={
                'class': 'input-field',
                'placeholder': '10-digit mobile number',
                'maxlength': '15',
                'inputmode': 'tel',
            }),
            'age': forms.NumberInput(attrs={'class': 'input-field', 'placeholder': 'Age (0–99)', 'min': 0, 'max': 99, 'oninput': 'if(parseInt(this.value)>99)this.value=99;if(this.value<0)this.value=0;'}),
            'gender': forms.RadioSelect(),
            'address': forms.Textarea(attrs={'class': 'input-field', 'rows': 2, 'placeholder': 'Address (optional)'}),
            'blood_group': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'e.g. B+'}),
            'allergies': forms.Textarea(attrs={'class': 'input-field', 'rows': 2, 'placeholder': 'Known allergies (optional)'}),
            'notes': forms.Textarea(attrs={'class': 'input-field', 'rows': 2, 'placeholder': 'Any standing notes (optional)'}),
        }


class VitalsForm(forms.ModelForm):
    """Quick vitals entry form shown on visit detail."""
    class Meta:
        model = Visit
        fields = ['vitals_bp', 'vitals_temp', 'vitals_weight', 'vitals_spo2', 'chief_complaint']
        widgets = {
            'vitals_bp': forms.TextInput(attrs={'class': 'input-field', 'placeholder': '120/80'}),
            'vitals_temp': forms.TextInput(attrs={'class': 'input-field', 'placeholder': '98.6°F'}),
            'vitals_weight': forms.TextInput(attrs={'class': 'input-field', 'placeholder': '70 kg'}),
            'vitals_spo2': forms.TextInput(attrs={'class': 'input-field', 'placeholder': '98%'}),
            'chief_complaint': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Reason for visit'}),
        }


class QuickVisitForm(forms.Form):
    """Add an existing patient directly to today's queue."""
    chief_complaint = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'input-field',
            'placeholder': 'Reason for visit today (optional)',
        }),
    )


class PatientEditForm(forms.ModelForm):
    """Edit existing patient demographics. Phone excluded — it's the lookup key."""
    class Meta:
        model = Patient
        fields = ['full_name', 'guardian_name', 'age', 'gender', 'address', 'blood_group', 'allergies', 'notes']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Patient full name'}),
            'guardian_name': forms.TextInput(attrs={'class': 'input-field', 'placeholder': "Husband's / Father's name (optional)"}),
            'age': forms.NumberInput(attrs={'class': 'input-field', 'placeholder': 'Age (0–99)', 'min': 0, 'max': 99, 'oninput': 'if(parseInt(this.value)>99)this.value=99;if(this.value<0)this.value=0;'}),
            'gender': forms.RadioSelect(),
            'address': forms.Textarea(attrs={'class': 'input-field', 'rows': 2, 'placeholder': 'Address (optional)'}),
            'blood_group': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'e.g. B+'}),
            'allergies': forms.Textarea(attrs={'class': 'input-field', 'rows': 2, 'placeholder': 'Known allergies (optional)'}),
            'notes': forms.Textarea(attrs={'class': 'input-field', 'rows': 2, 'placeholder': 'Any standing notes (optional)'}),
        }
