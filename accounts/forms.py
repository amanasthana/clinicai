from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import make_password
from .models import Clinic, StaffMember, ClinicRegistrationRequest, ContactMessage


class StyledAuthForm(AuthenticationForm):
    """Login form with Tailwind-compatible widget attrs."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'input-field',
            'placeholder': 'Mobile number or Username',
            'autofocus': True,
        })
        self.fields['password'].widget.attrs.update({
            'class': 'input-field',
            'placeholder': 'Password',
        })


class ClinicSetupForm(forms.ModelForm):
    """First-time clinic registration form."""
    class Meta:
        model = Clinic
        fields = ['name', 'address', 'city', 'state', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'e.g. City Health Clinic'}),
            'address': forms.Textarea(attrs={'class': 'input-field', 'rows': 2, 'placeholder': 'Street address'}),
            'city': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'State'}),
            'phone': forms.TextInput(attrs={'class': 'input-field', 'placeholder': '10-digit phone'}),
        }


class AdminUserForm(forms.Form):
    """Create the first admin/doctor user for a new clinic."""
    first_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'First name'}),
    )
    last_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Last name'}),
    )
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Username for login'}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'input-field', 'placeholder': 'doctor@example.com (optional — needed for password reset)'}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'input-field', 'placeholder': 'Set a password'}),
        min_length=8,
    )
    display_name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Dr. Full Name'}),
    )
    qualification = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'MBBS, MD (optional)'}),
    )
    registration_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Medical council reg. no. (optional)'}),
    )

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username


class AddStaffForm(forms.Form):
    """Add a new staff member to the clinic."""
    first_name = forms.CharField(max_length=50, widget=forms.TextInput(attrs={'class': 'input-field'}))
    last_name = forms.CharField(max_length=50, widget=forms.TextInput(attrs={'class': 'input-field'}))
    phone = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'input-field', 'placeholder': '10-digit mobile number',
            'inputmode': 'numeric', 'maxlength': '10', 'id': 'staff-phone',
        }),
        help_text="Staff member's mobile number. Used to build their login User ID.",
    )
    username = forms.CharField(
        max_length=150,
        min_length=6,
        widget=forms.TextInput(attrs={'class': 'input-field', 'id': 'staff-username'}),
        help_text='Auto-filled from phone + first name. You may customise it. Minimum 6 characters.',
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'input-field', 'placeholder': 'staff@example.com (optional — needed for password reset)'}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'input-field', 'placeholder': 'Minimum 8 characters'}),
        min_length=8,
    )
    display_name = forms.CharField(max_length=120, widget=forms.TextInput(attrs={'class': 'input-field'}))
    role = forms.ChoiceField(
        choices=StaffMember.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'input-field'}),
    )
    qualification = forms.CharField(
        max_length=200, required=False, widget=forms.TextInput(attrs={'class': 'input-field'})
    )
    registration_number = forms.CharField(
        max_length=50, required=False, widget=forms.TextInput(attrs={'class': 'input-field'})
    )
    access_expires_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'input-field', 'type': 'date'}),
        help_text='Leave blank for permanent access. Set a date to auto-expire this login.',
    )

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not phone.isdigit() or len(phone) != 10:
            raise forms.ValidationError('Enter a valid 10-digit mobile number.')
        return phone

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if len(username) < 6:
            raise forms.ValidationError('User ID must be at least 6 characters.')
        if '__' in username:
            raise forms.ValidationError('User ID cannot contain double underscore (__).')
        # Check global uniqueness — the username must be unique across all clinics
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('This User ID is already taken. Choose a different one.')
        return username


class ClinicRegistrationForm(forms.Form):
    # Clinic info
    clinic_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'e.g. Sharma Clinic, City Health Centre'}),
    )
    clinic_type = forms.ChoiceField(
        choices=ClinicRegistrationRequest.CLINIC_TYPES,
        widget=forms.Select(attrs={'class': 'input-field'}),
    )
    city = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'City'}),
    )
    state = forms.CharField(
        max_length=100,
        initial='Maharashtra',
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'State'}),
    )
    clinic_phone = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Clinic phone number', 'inputmode': 'tel'}),
    )

    # Doctor info
    doctor_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Dr. Full Name'}),
    )
    qualification = forms.CharField(
        max_length=200, required=False,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'MBBS, MD — optional'}),
    )
    registration_number = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Medical Council Reg. No. — optional'}),
    )

    # Login credentials
    phone = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={'class': 'input-field', 'placeholder': '10-digit mobile number', 'inputmode': 'numeric', 'maxlength': '10'}),
        help_text='This will be your login username.',
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'input-field', 'placeholder': 'doctor@example.com'}),
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={'class': 'input-field', 'placeholder': 'At least 8 characters'}),
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'input-field', 'placeholder': 'Repeat password'}),
    )

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not phone.isdigit() or len(phone) != 10:
            raise forms.ValidationError('Enter a valid 10-digit mobile number.')
        if User.objects.filter(username=phone).exists():
            raise forms.ValidationError('A clinic with this mobile number is already registered.')
        if ClinicRegistrationRequest.objects.filter(phone=phone, status='pending').exists():
            raise forms.ValidationError('A registration request with this number is already pending review.')
        return phone

    def clean(self):
        cd = super().clean()
        pw = cd.get('password')
        pw2 = cd.get('password_confirm')
        if pw and pw2 and pw != pw2:
            self.add_error('password_confirm', 'Passwords do not match.')
        return cd

    def save(self):
        cd = self.cleaned_data
        return ClinicRegistrationRequest.objects.create(
            clinic_name=cd['clinic_name'],
            clinic_type=cd['clinic_type'],
            city=cd['city'],
            state=cd['state'],
            clinic_phone=cd['clinic_phone'],
            doctor_name=cd['doctor_name'],
            qualification=cd.get('qualification', ''),
            registration_number=cd.get('registration_number', ''),
            phone=cd['phone'],
            email=cd.get('email', ''),
            password_hash=make_password(cd['password']),
        )


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'phone', 'inquiry_type', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Your name'}),
            'email': forms.EmailInput(attrs={'class': 'input-field', 'placeholder': 'your@email.com'}),
            'phone': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Mobile number (optional)', 'inputmode': 'tel'}),
            'inquiry_type': forms.Select(attrs={'class': 'input-field'}),
            'message': forms.Textarea(attrs={
                'class': 'input-field', 'rows': 4,
                'placeholder': 'Tell us about your clinic, what you need, or any questions you have...',
            }),
        }
