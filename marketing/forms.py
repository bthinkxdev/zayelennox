"""Django forms for the marketing app."""

from __future__ import annotations

from django import forms


class NewsletterSignupForm(forms.Form):
    """Public-facing newsletter signup form."""

    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "you@example.com"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]

        # Django's EmailField only checks RFC syntax, so "abc@123.com" passes even
        # though a purely numeric domain label is almost always throwaway/fake input.
        # Reject any domain whose label (other than the final TLD) is all digits.
        domain = email.rsplit("@", 1)[-1]
        labels = domain.split(".")[:-1]
        if any(label.isdigit() for label in labels):
            raise forms.ValidationError("Please enter a valid email address.")

        return email