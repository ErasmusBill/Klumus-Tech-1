from django import forms
from django.forms import ModelForm
from .models import *
from django.contrib.auth import get_user_model



User = get_user_model()

class SchoolRegistrationForm(forms.Form):
    school_name = forms.CharField(max_length=255, label="School Name")
    school_logo = forms.ImageField(required=False, label="School Logo")
    location = forms.CharField(max_length=255, label="Location / Address")
    phone_number = forms.CharField(max_length=20, label="School Phone")
    address = forms.CharField(max_length=20, label="address")
    postal_code = forms.CharField(max_length=20,label="Postal code")
    email = forms.EmailField()
    created_at = forms.DateField()
    updated_at = forms.DateField()


    admin_username = forms.CharField(max_length=150, label="Admin Username")
    admin_full_name = forms.CharField(max_length=150, label="Admin Full Name")
    admin_email = forms.EmailField(label="Admin Email")
    admin_phone = forms.CharField(max_length=20, label="Admin Phone Number")
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")

    def clean_school_name(self):
        school_name = self.cleaned_data.get("school_name")
        if School.objects.filter(name__iexact=school_name).exists():
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
        
        return cleaned_data


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
        return cleaned_data