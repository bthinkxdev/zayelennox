"""Domain exceptions for the cart app."""

from __future__ import annotations


class CartError(Exception):
    """Base exception for cart services."""


class CartNotFoundError(CartError):
    """Raised when no cart can be resolved for the request context."""


class CartItemNotFoundError(CartError):
    """Raised when a cart line item cannot be resolved for the given cart."""


class InsufficientStockError(CartError):
    """Raised when a requested quantity exceeds available stock."""


class VariantRequiredError(CartError):
    """
    Raised when adding a product that has variants without resolving one.

    Products with variants don't sell against their own stock_quantity (it
    isn't maintained once variants exist - see Product.is_in_stock); a
    missing/invalid variant_id must be rejected here rather than silently
    falling back to the product's stock figure.
    """


class ComboLineNotAdjustableError(CartError):
    """
    Raised when trying to change the quantity of a single combo component.

    Combo lines are priced as a prorated share of the combo's fixed price
    (see cart.services.add_combo_to_cart) — adjusting one component's
    quantity independently would desync it from its siblings and invalidate
    that pricing. Remove and re-add the combo at a different quantity
    instead (see cart.services.remove_combo_from_cart).
    """