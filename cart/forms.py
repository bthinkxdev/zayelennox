"""Django forms for the cart app."""

from __future__ import annotations

from django import forms


class CartQuantityForm(forms.Form):
    """Increment/decrement a single cart line by a +1/-1 delta."""

    cart_item_id = forms.IntegerField(min_value=1)
    delta = forms.IntegerField(min_value=-1, max_value=1)


class CartCouponForm(forms.Form):
    """Apply a coupon code to the cart."""

    code = forms.CharField(max_length=40, min_length=1)


class CartComboForm(forms.Form):
    """Identify a combo in the cart (add / remove)."""

    combo_id = forms.IntegerField(min_value=1)


class CartComboQuantityForm(CartComboForm):
    """Add or remove one whole combo (+1/-1)."""

    delta = forms.IntegerField(min_value=-1, max_value=1)
