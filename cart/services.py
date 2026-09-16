"""Write operations and business rules for the cart app."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.db import transaction
from django.http import HttpRequest

from cart.exceptions import (
    CartItemNotFoundError,
    ComboLineNotAdjustableError,
    InsufficientStockError,
    VariantRequiredError,
)
from cart.models import Cart, CartItem
from cart.selectors import get_buy_now_cart_for_request, get_cart_for_request, get_cart_summary
from catalog.models import Combo, Product, ProductVariant
from catalog.selectors import get_variant_price
from core.selectors import get_default_currency
from delivery.models import City
from delivery.selectors import get_delivery_charge
from marketing.services import validate_coupon_for_cart


def _resolve_unit_price(*, product: Product, variant: Optional[ProductVariant], user: Optional[Any] = None, quantity: int = 1
) -> Decimal:
    """Compute snapshotted unit price from catalog selector."""
    price_data = get_variant_price(
        product_id=product.pk,
        variant_id=variant.pk if variant else None,
        user=user,
        quantity=quantity,
    )
    return Decimal(price_data["price"])


@transaction.atomic
def get_or_create_cart(*, request: HttpRequest) -> Cart:
    """
    Return the persistent cart for the request, creating one when missing.

    Authenticated customers receive a profile-linked cart; guests use session_key.
    """
    if not request.session.session_key:
        request.session.create()

    existing = get_cart_for_request(request=request)
    if existing:
        if not request.user.is_authenticated:
            request.session["guest_cart_id"] = existing.pk
        return existing

    currency = get_default_currency()
    if currency is None:
        raise RuntimeError("No default currency configured.")

    if request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        return Cart.objects.create(
            customer_profile=request.user.customer_profile,
            currency=currency,
            is_buy_now=False,
        )
    cart = Cart.objects.create(
        session_key=request.session.session_key,
        currency=currency,
        is_buy_now=False,
    )
    request.session["guest_cart_id"] = cart.pk
    return cart


@transaction.atomic
def get_or_create_buy_now_cart(*, request: HttpRequest) -> Cart:
    """
    Return the isolated single-item "Buy Now" cart for the request, creating one when missing.

    This is a distinct ``Cart`` row from the persistent cart returned by
    ``get_or_create_cart`` — Buy Now must never read from or write to the
    customer's real cart, and vice versa. Deliberately does NOT set
    ``request.session["guest_cart_id"]``, since that key is reserved for the
    persistent guest cart merged on login (``merge_carts``).
    """
    if not request.session.session_key:
        request.session.create()

    existing = get_buy_now_cart_for_request(request=request)
    if existing:
        return existing

    currency = get_default_currency()
    if currency is None:
        raise RuntimeError("No default currency configured.")

    if request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        return Cart.objects.create(
            customer_profile=request.user.customer_profile,
            currency=currency,
            is_buy_now=True,
        )
    return Cart.objects.create(
        session_key=request.session.session_key,
        currency=currency,
        is_buy_now=True,
    )


@transaction.atomic
def clear_cart(*, cart: Cart) -> None:
    """Remove all line items from a cart without deleting the cart row itself."""
    CartItem.objects.filter(cart=cart).delete()


@transaction.atomic
def reset_cart(*, cart: Cart) -> None:
    """
    Empty a cart's line items and clear any coupon/delivery state on it.

    """
    clear_cart(cart=cart)
    if cart.coupon_code or cart.coupon_discount or cart.delivery_charge or cart.destination_city_id:
        cart.coupon_code = ""
        cart.coupon_discount = Decimal("0.00")
        cart.delivery_charge = Decimal("0.00")
        cart.destination_city = None
        cart.save(
            update_fields=[
                "coupon_code",
                "coupon_discount",
                "delivery_charge",
                "destination_city",
                "updated_at",
            ]
        )


@transaction.atomic
def set_buy_now_item(
    *,
    cart: Cart,
    product: Product,
    variant: Optional[ProductVariant] = None,
    quantity: int = 1,
) -> CartItem:
    """
    Replace the contents of a Buy Now cart with exactly one line item.

    Buy Now always represents a single, current purchase intent — any item,
    coupon, or delivery-charge state left over from a previous Buy Now click
    is cleared first, so each click is a fresh, isolated selection
    independent of both past Buy Now attempts and the persistent cart.
    """
    reset_cart(cart=cart)
    return add_to_cart(cart=cart, product=product, variant=variant, quantity=quantity, overwrite=True)


@transaction.atomic
def add_to_cart(
    *,
    cart: Cart,
    product: Product,
    variant: Optional[ProductVariant] = None,
    quantity: int = 1,
    overwrite: bool = False,
    combo: Optional[Combo] = None,
    unit_price_override: Optional[Decimal] = None,
) -> CartItem:
    """
    Add or increment a cart line, or overwrite exactly.

    Args:
        combo: When set, this line is a component of a product combo — it's
            kept on a separate cart row from any standalone line of the same
            product/variant (see the unique constraint on CartItem), and its
            price comes from ``unit_price_override`` rather than the live
            catalog price.
        unit_price_override: Explicit unit price to snapshot instead of
            resolving one from the catalog. Used exclusively by
            ``add_combo_to_cart`` for its prorated per-component price.

    Raises:
        VariantRequiredError: The product has variants but none was resolved
            (missing/invalid variant_id) - it can't be sold against its own
            stock_quantity once variants exist.
        InsufficientStockError: Requested quantity exceeds available stock.
    """
    if variant is None and product.variants.exists():
        raise VariantRequiredError(
            "Please select an option (e.g. size or color) before adding this product to your cart."
        )

    user = (
        cart.customer_profile.user
        if (cart.customer_profile and cart.customer_profile.user_id)
        else None
    )

    # Lock the cart row itself: without it, two concurrent add-to-cart
    # requests for the same (cart, product, variant, combo) can both miss
    # the lookup below (no matching row yet) and each INSERT their own —
    # the unique constraint can't catch that itself since combo (and
    # variant, for a product with no variants) is NULL, and most databases
    # don't treat two NULLs as equal for uniqueness. Locking the cart
    # serializes concurrent adds to it so the second request always sees
    # the first's row before deciding whether to create or merge.
    Cart.objects.select_for_update().get(pk=cart.pk)

    item = CartItem.objects.filter(cart=cart, product=product, variant=variant, combo=combo).first()

    if item:
        new_quantity = quantity if overwrite else item.quantity + quantity
    else:
        new_quantity = quantity

    max_stock = variant.stock_quantity if variant else product.stock_quantity
    if new_quantity > max_stock:
        raise InsufficientStockError(f"Only {max_stock} items available in stock.")

    if unit_price_override is not None:
        unit_price = unit_price_override
    else:
        unit_price = _resolve_unit_price(product=product, variant=variant, user=user, quantity=new_quantity)

    if item:
        item.quantity = new_quantity
        item.unit_price_at_add = unit_price
        item.save(update_fields=["quantity", "unit_price_at_add", "updated_at"])
    else:
        item = CartItem.objects.create(
            cart=cart,
            product=product,
            variant=variant,
            quantity=quantity,
            unit_price_at_add=unit_price,
            combo=combo,
            combo_name_snapshot=combo.name if combo else "",
        )

    return item


@transaction.atomic
def add_combo_to_cart(*, cart: Cart, combo: Combo, quantity: int = 1) -> list[CartItem]:
    """
    Add every component of a combo to the cart as its own line, at a
    prorated share of the combo's fixed price.

    The discount between ``combo.combo_price`` and the sum of the
    components' normal prices is split across components proportionally to
    their own normal price, so each product's HSN/GST taxable value stays
    correct — a combo itself is never a taxable line. All-or-nothing: if any
    component can't be added (out of stock, missing variant), the whole
    call raises and nothing is added.

    Raises:
        VariantRequiredError: A component product needs a variant selection.
        InsufficientStockError: A component doesn't have enough stock, or
            ``quantity`` isn't a positive number.
    """
    if quantity < 1:
        raise InsufficientStockError("Quantity must be at least 1.")

    combo_items = list(combo.items.select_related("product", "variant"))
    if not combo_items:
        raise InsufficientStockError("This combo has no products configured.")

    user = (
        cart.customer_profile.user
        if (cart.customer_profile and cart.customer_profile.user_id)
        else None
    )

    normal_line_totals: list[Decimal] = []
    for combo_item in combo_items:
        line_quantity = combo_item.quantity * quantity
        normal_unit_price = _resolve_unit_price(
            product=combo_item.product,
            variant=combo_item.variant,
            user=user,
            quantity=line_quantity,
        )
        normal_line_totals.append(normal_unit_price * line_quantity)

    total_normal = sum(normal_line_totals)
    combo_total = combo.combo_price * quantity

    if total_normal <= 0:
        prorated_line_totals = [Decimal("0.00") for _ in combo_items]
    else:
        prorated_line_totals = [
            (line_total / total_normal * combo_total).quantize(Decimal("0.01"))
            for line_total in normal_line_totals
        ]
        # Correct rounding drift on the last line so the lines sum to
        # exactly combo_total (paise-level remainder from quantize above).
        remainder = combo_total - sum(prorated_line_totals)
        prorated_line_totals[-1] += remainder

    added_items: list[CartItem] = []
    for combo_item, line_total in zip(combo_items, prorated_line_totals):
        line_quantity = combo_item.quantity * quantity
        # CartItem stores one unit_price for the whole line, so a combo
        # component with quantity > 1 can lose or gain a paisa or two here
        # if line_total doesn't divide evenly — bounded to a few paise per
        # such line and self-consistent from this point on (every downstream
        # total is summed from these stored unit prices, never recomputed
        # against combo_price), the same tolerance any per-unit-priced cart
        # line has when splitting a discount across a quantity.
        unit_price = (line_total / line_quantity).quantize(Decimal("0.01"))
        added_items.append(
            add_to_cart(
                cart=cart,
                product=combo_item.product,
                variant=combo_item.variant,
                quantity=line_quantity,
                combo=combo,
                unit_price_override=unit_price,
            )
        )
    return added_items


@transaction.atomic
def remove_combo_from_cart(*, cart: Cart, combo_id: int) -> None:
    """Remove every cart line that was added as part of the given combo."""
    CartItem.objects.filter(cart=cart, combo_id=combo_id).delete()


@transaction.atomic
def remove_cart_item(*, cart: Cart, cart_item_id: int) -> Optional[int]:
    """Remove a line item from the cart. Returns product_id if completely removed."""
    item = CartItem.objects.filter(cart=cart, pk=cart_item_id).first()
    if item:
        product_id = item.product_id
        item.delete()
        if not CartItem.objects.filter(cart=cart, product_id=product_id).exists():
            return product_id
    return None

@transaction.atomic
def adjust_cart_item_quantity(
    *,
    cart: Cart,
    cart_item_id: int,
    delta: int,
) -> Optional[CartItem]:
    """
    Increment or decrement a cart line's quantity by ``delta``.

    Row-locked (``select_for_update``) so rapid +/- clicks never race each
    other into a lost update. Quantity dropping to zero or below deletes the
    line instead of persisting a non-positive quantity.

    Returns:
        The updated CartItem, or None if the line was deleted.

    Raises:
        CartItemNotFoundError: When no matching line exists on this cart.
        ComboLineNotAdjustableError: The line is a combo component — its
            quantity is fixed at add-time (see add_combo_to_cart); remove
            and re-add the combo instead of adjusting one line.
    """
    item = CartItem.objects.select_for_update().filter(cart=cart, pk=cart_item_id).first()
    if item is None:
        raise CartItemNotFoundError("Cart item not found.")
    if item.combo_id:
        raise ComboLineNotAdjustableError(
            "This item is part of a combo — remove the whole combo to change it."
        )

    new_quantity = item.quantity + delta
    if new_quantity < 1:
        new_quantity = 1

    max_stock = item.variant.stock_quantity if item.variant else item.product.stock_quantity
    if new_quantity > max_stock:
        if delta > 0 or max_stock < 1:
            raise InsufficientStockError(f"Only {max_stock} items available in stock.")

        new_quantity = max_stock

    user = (
        cart.customer_profile.user
        if (cart.customer_profile and cart.customer_profile.user_id)
        else None
    )
    unit_price = _resolve_unit_price(
        product=item.product,
        variant=item.variant,
        user=user,
        quantity=new_quantity,
    )

    item.quantity = new_quantity
    item.unit_price_at_add = unit_price
    item.save(update_fields=["quantity", "unit_price_at_add", "updated_at"])
    return item

@transaction.atomic
def apply_coupon(*, cart: Cart, code: str) -> Cart:
    """
    Validate and apply a coupon via the marketing service boundary.

    Raises:
        InvalidCouponError: Propagated from marketing.services.
    """
    summary = get_cart_summary(cart=cart)
    category_ids = [line.product.category_id for line in summary.lines]
    result = validate_coupon_for_cart(
        code=code,
        cart_subtotal=summary.subtotal,
        customer_profile_id=cart.customer_profile_id,
        cart_category_ids=category_ids,
    )
    cart.coupon_code = result["code"]
    cart.coupon_discount = result["discount_amount"]
    cart.save(update_fields=["coupon_code", "coupon_discount", "updated_at"])
    return cart

@transaction.atomic
def remove_coupon(*, cart: Cart) -> Cart:
    """Clear any applied coupon from the cart."""
    cart.coupon_code = ""
    cart.coupon_discount = Decimal("0.00")
    cart.save(update_fields=["coupon_code", "coupon_discount", "updated_at"])
    return cart

@transaction.atomic
def recalculate_delivery_charge(*, cart: Cart, destination_city: City) -> Cart:
    """Persist delivery charge for a destination city via delivery selector."""
    summary = get_cart_summary(cart=cart)
    charge = get_delivery_charge(
        item_count=summary.item_count,
        destination_city=destination_city,
    )
    cart.destination_city = destination_city
    cart.delivery_charge = charge
    cart.save(update_fields=["destination_city", "delivery_charge", "updated_at"])
    return cart


def toggle_wishlist(*, request: HttpRequest, product_id: int) -> bool:
    """
    Toggle a product in the persistent wishlist (DB-backed, guest or authenticated).

    Returns:
        True if product is now in wishlist, False if removed.
    """
    from accounts.models import WishlistItem
    from accounts.subscription_services import (
        add_to_wishlist,
        get_or_create_wishlist,
        remove_from_wishlist,
    )

    wishlist = get_or_create_wishlist(request=request)
    if not request.user.is_authenticated:
        request.session["guest_wishlist_id"] = wishlist.pk
    exists = WishlistItem.objects.filter(wishlist=wishlist, product_id=product_id).exists()
    if exists:
        remove_from_wishlist(wishlist=wishlist, product_id=product_id)
        return False
    add_to_wishlist(wishlist=wishlist, product_id=product_id)
    return True


@transaction.atomic
def merge_carts(*, guest_cart: Cart, user_profile) -> None:
    """Merge the guest cart items into the user's profile cart."""
    user_cart = Cart.objects.filter(customer_profile=user_profile, is_buy_now=False).first()

    if not user_cart:
        guest_cart.customer_profile = user_profile
        guest_cart.session_key = None
        guest_cart.save(update_fields=["customer_profile", "session_key", "updated_at"])
        return

    if guest_cart.pk == user_cart.pk:
        return

    for item in guest_cart.items.all():
        user_item = user_cart.items.filter(
            product=item.product,
            variant=item.variant,
        ).first()
        if user_item:
            user_item.quantity += item.quantity
            user_item.save(update_fields=["quantity", "updated_at"])
            item.delete()
        else:
            item.cart = user_cart
            item.save(update_fields=["cart", "updated_at"])

    guest_cart.delete()


@transaction.atomic
def merge_wishlists(*, guest_wishlist, user_profile) -> None:
    """Merge guest wishlist items into the user's profile wishlist."""
    from accounts.models import Wishlist
    user_wishlist = Wishlist.objects.filter(customer_profile=user_profile).first()
    if not user_wishlist:
        guest_wishlist.customer_profile = user_profile
        guest_wishlist.session_key = None
        guest_wishlist.save(update_fields=["customer_profile", "session_key", "updated_at"])
        return

    if guest_wishlist.pk == user_wishlist.pk:
        return

    for item in guest_wishlist.items.all():
        exists = user_wishlist.items.filter(product=item.product).exists()
        if exists:
            item.delete()
        else:
            item.wishlist = user_wishlist
            item.save(update_fields=["wishlist", "updated_at"])

    guest_wishlist.delete()
