from django import forms
from django.forms import ModelForm
from .models import *
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password



User = get_user_model()
FREE_TRIAL_DAYS = getattr(settings, "FREE_TRIAL_DAYS", 30)


class SchoolInterestForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_package"].queryset = Package.objects.filter(is_active=True).order_by("price")

    class Meta:
        model = SchoolOnboardingRequest
        fields = [
            "school_name",
            "contact_full_name",
            "contact_role",
            "contact_email",
            "contact_phone",
            "location",
            "address",
            "postal_code",
            "website",
            "school_size",
            "preferred_package",
            "message",
        ]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 4}),
        }

    

class SchoolProvisionForm(forms.Form):
    school_name = forms.CharField(max_length=255, label="School Name")
    school_logo = forms.ImageField(required=False, label="School Logo")
    location = forms.CharField(max_length=255, label="Location / Address")
    phone_number = forms.CharField(max_length=20, label="School Phone")
    address = forms.CharField(max_length=255, label="Address")
    postal_code = forms.CharField(max_length=20, label="Postal code", required=False)
    email = forms.EmailField(label="School Email")
    website = forms.URLField(required=False, label="School Website")
    trial_days = forms.IntegerField(
        min_value=FREE_TRIAL_DAYS,
        max_value=FREE_TRIAL_DAYS,
        initial=FREE_TRIAL_DAYS,
        label="Trial Days (Fixed 1 Month)",
        disabled=True,
    )

    admin_username = forms.CharField(max_length=150, label="Admin Username")
    admin_full_name = forms.CharField(max_length=150, label="Admin Full Name")
    admin_email = forms.EmailField(label="Admin Email")
    admin_phone = forms.CharField(max_length=20, label="Admin Phone Number")
    password = forms.CharField(widget=forms.PasswordInput, label="Temporary Password", initial="Abc@12345")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm Password", initial="Abc@12345")

    def __init__(self, *args, inquiry=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.inquiry = inquiry

    def clean_school_name(self):
        school_name = self.cleaned_data.get("school_name")
        existing = School.objects.filter(name__iexact=school_name)
        if self.inquiry and self.inquiry.provisioned_school_id:
            existing = existing.exclude(id=self.inquiry.provisioned_school_id)
        if existing.exists():
            raise forms.ValidationError("A school with this name already exists.")
        return school_name

    def clean_admin_username(self):
        username = self.cleaned_data.get("admin_username")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_admin_email(self):
        email = self.cleaned_data.get("admin_email")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email is already registered.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        if password:
            validate_password(password)

        return cleaned_data

    def clean_trial_days(self):
        return FREE_TRIAL_DAYS


class ParentForm(forms.ModelForm):
    class Meta:
        model = Parent
        fields = [
            "father_name", "father_phone", "father_occupation", "father_email",
            "mother_name", "mother_phone", "mother_occupation", "mother_email",
            "present_address", "permanent_address",
        ]




class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ["school", "package", "start_date", "is_trial"]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
        }



class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput, label="Current password")
    new_password = forms.CharField(widget=forms.PasswordInput, label="New password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password != confirm_password:
            raise forms.ValidationError("Passwords do not match.")
        if new_password and len(new_password) < 8:
            raise forms.ValidationError("Password must be at least 8 characters long.")
        if new_password:
            validate_password(new_password)
        return cleaned_data
    

class PasswordRequestForm(forms.Form):
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(
            attrs={
                "placeholder": "Enter your registered email",
                "class": "form-control",
            }
        ),
    )

        
class PasswordResetForm(forms.Form):
    """Form for setting a new password after verifying token"""
    new_password = forms.CharField(
        widget=forms.PasswordInput,
        label="New Password",
        min_length=8,
        help_text="Password must be at least 8 characters long."
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm New Password"
    )

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError("Passwords do not match.")
        if new_password:
            validate_password(new_password)
        return cleaned_data
