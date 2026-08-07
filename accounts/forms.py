"""Django forms for the accounts app."""

from __future__ import annotations

import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from recurring.models import RecurrenceFrequency
from accounts.models import Address

# Indian mobile numbers: 10 digits, first digit 6-9 (no STD/country code).
INDIA_PHONE_RE = re.compile(r'^[6-9]\d{9}$')
PINCODE_RE = re.compile(r'^[1-9][0-9]{5}$')
ONLY_DIGITS_RE = re.compile(r'^\d+$')


class EmailLoginForm(AuthenticationForm):
    """Email/password login form using email as the username field."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "class": "form-control"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "class": "form-control"}
        ),
    )


class OTPRequestForm(forms.Form):
    """Form to request an OTP for phone-based authentication."""

    phone = forms.CharField(
        max_length=20,
        label="Phone number",
        widget=forms.TextInput(attrs={"autocomplete": "tel"}),
    )
    purpose = forms.ChoiceField(
        choices=[
            ("login", "Login"),
            ("signup", "Sign Up"),
            ("password_reset", "Password Reset"),
        ],
        label="Purpose",
    )


class OTPVerifyForm(forms.Form):
    """Form to verify a submitted OTP code."""

    phone = forms.CharField(max_length=20, label="Phone number")
    otp_code = forms.CharField(max_length=6, min_length=6, label="OTP code")
    purpose = forms.ChoiceField(
        choices=[
            ("login", "Login"),
            ("signup", "Sign Up"),
            ("password_reset", "Password Reset"),
        ],
        label="Purpose",
    )


class EmailRegistrationForm(forms.Form):
    """Form for email-based customer registration."""

    email = forms.EmailField(label="Email")
    password = forms.CharField(
        widget=forms.PasswordInput,
        min_length=8,
        label="Password",
    )
    name = forms.CharField(max_length=150, label="Full name")


class GoogleLoginForm(forms.Form):
    """Form accepting a Google ID token from the client."""

    id_token = forms.CharField(widget=forms.HiddenInput)


class GuestCheckoutForm(forms.Form):
    """Form to issue a guest checkout token for a cart session."""

    cart_id = forms.CharField(max_length=64, label="Cart ID")


class ForgotPasswordForm(forms.Form):
    """Form to initiate password reset via OTP."""

    phone = forms.CharField(max_length=20, label="Phone number")


class ResetPasswordForm(forms.Form):
    """Form to set a new password after OTP verification."""

    phone = forms.CharField(max_length=20, label="Phone number")
    otp_code = forms.CharField(max_length=6, min_length=6, label="OTP code")
    new_password = forms.CharField(widget=forms.PasswordInput, min_length=8, label="New password")


class ForgotPasswordEmailForm(forms.Form):
    """Form to initiate password reset via email OTP."""

    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if not User.objects.filter(email=email).exists():
            raise forms.ValidationError("No account is registered with this email address.")
        return email


class ResetPasswordEmailForm(forms.Form):
    """Form to reset password after email OTP verification."""

    email = forms.EmailField(widget=forms.HiddenInput())
    otp_code = forms.CharField(
        max_length=4,
        min_length=4,
        label="4-Digit OTP Code",
        widget=forms.TextInput(attrs={
            "class": "form-control text-center fs-2 letter-spacing-lg",
            "placeholder": "• • • •",
            "autocomplete": "one-time-code",
            "maxlength": "4",
        }),
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "New Password"}),
        min_length=8,
        label="New Password",
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirm Password"}),
        min_length=8,
        label="Confirm Password",
    )

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")
        if new_password and confirm_password and new_password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data


class AddressForm(forms.ModelForm):
    """Create or update a customer delivery address."""

    pincode = forms.RegexField(
        regex=r"^[1-9][0-9]{5}$",
        error_messages={"invalid": "Enter a valid 6-digit Indian pincode."},
        label="Pincode",
    )

    class Meta:
        model = Address
        fields = ("label", "line1", "line2", "city", "pincode", "is_default")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        from delivery.models import City

        self.fields["city"].queryset = City.objects.filter(is_active=True)


class SubscriptionCreateForm(forms.Form):
    product_id = forms.IntegerField(widget=forms.HiddenInput)
    delivery_address_id = forms.ModelChoiceField(
        queryset=Address.objects.none(),
        label="Delivery address",
    )
    frequency = forms.ChoiceField(choices=RecurrenceFrequency.choices, label="Frequency")
    next_run_date = forms.DateField(
        label="First delivery date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    quantity = forms.IntegerField(min_value=1, initial=1, label="Quantity")

    def __init__(self, *args, customer_profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        if customer_profile is not None:
            self.fields["delivery_address_id"].queryset = Address.objects.filter(
                customer_profile=customer_profile
            )


class EmailOTPRequestForm(forms.Form):
    """Form to request an OTP for email-based login/signup."""

    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "you@example.com"}),
    )


class EmailOTPVerifyForm(forms.Form):
    """Form to verify an email OTP code."""

    email = forms.EmailField(widget=forms.HiddenInput())
    otp_code = forms.CharField(
        max_length=4,
        min_length=4,
        label="4-Digit OTP Code",
        widget=forms.TextInput(attrs={
            "class": "form-control text-center fs-2 letter-spacing-lg",
            "placeholder": "• • • •",
            "autocomplete": "one-time-code",
            "maxlength": "4",
        }),
    )

class CustomerProfileEditForm(forms.Form):
    """
    Form to edit retail customer profile and default address.

    """

    name = forms.CharField(max_length=150, label="Full name", widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="Email", required=False, widget=forms.EmailInput(attrs={"class": "form-control", "readonly": True}))
    phone = forms.CharField(
        max_length=20,
        label="Phone number",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric", "maxlength": "10", "placeholder": "10-digit mobile number"}),
    )

    address_line1 = forms.CharField(max_length=255, label="Address Line 1", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    address_line2 = forms.CharField(max_length=255, label="Address Line 2", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    city_name = forms.CharField(max_length=120, label="City / Town", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    state_name = forms.CharField(max_length=120, label="State", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    pincode = forms.CharField(
        max_length=10,
        label="Pincode",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric", "maxlength": "6"}),
    )

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if name and ONLY_DIGITS_RE.match(name):
            raise forms.ValidationError("Name cannot be only numbers.")
        return name

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            return phone
        if not ONLY_DIGITS_RE.match(phone):
            raise forms.ValidationError("Phone number can only contain numbers.")
        if not INDIA_PHONE_RE.match(phone):
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number (must start with 6-9).")
        return phone

    def clean_address_line1(self):
        line1 = (self.cleaned_data.get("address_line1") or "").strip()
        if line1 and ONLY_DIGITS_RE.match(line1):
            raise forms.ValidationError("Address Line 1 cannot be only numbers.")
        return line1

    def clean_pincode(self):
        pincode = (self.cleaned_data.get("pincode") or "").strip()
        if pincode and not PINCODE_RE.match(pincode):
            raise forms.ValidationError("Enter a valid 6-digit pincode.")
        return pincode

    def clean(self):
        cleaned = super().clean()
        # If the customer is entering/editing a default address, require the
        # rest of it too - mirrors checkout's delivery-detail validation.
        if cleaned.get("address_line1"):
            if not cleaned.get("city_name"):
                self.add_error("city_name", "City is required.")
            if not cleaned.get("state_name"):
                self.add_error("state_name", "State is required.")
            if not cleaned.get("pincode"):
                self.add_error("pincode", "Pincode is required.")
        return cleaned
