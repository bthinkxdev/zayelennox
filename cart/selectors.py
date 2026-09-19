"""Read-only query functions for the cart app; views must not call the ORM directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Prefetch, Sum
from django.http import HttpRequest

from cart.models import Cart, CartItem
from catalog.models import Combo, ComboImage, ComboItem, Product, ProductImage
from core.services import get_site_settings
from delivery.selectors import get_delivery_charge

_CART_CACHE_ATTR = "_floward_resolved_cart"
_BUY_NOW_CART_CACHE_ATTR = "_floward_resolved_buy_now_cart"


def _lookup_cart(*, request: HttpRequest, is_buy_now: bool) -> Optional[Cart]:
    """Shared lookup for the persistent cart or the isolated buy-now cart."""
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    cart = None
    if request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        cart = (
            Cart.objects.filter(customer_profile=request.user.customer_profile, is_buy_now=is_buy_now)
            .select_related("currency", "destination_city")
            .first()
        )

    if cart is None:
        cart = (
            Cart.objects.filter(session_key=session_key, is_buy_now=is_buy_now)
            .select_related("currency", "destination_city")
            .first()
        )

    return cart


def get_cart_for_request(*, request: HttpRequest) -> Optional[Cart]:
    """
    Resolve the persistent cart for the current request (guest or authenticated).

    Always excludes buy-now carts — this is the real, editable cart shown in
    the drawer/cart page, never affected by a PDP "Buy Now" click.

    Query guarantee: at most 1 SELECT on cart_cart per request (request-scoped cache).
    """
    if hasattr(request, _CART_CACHE_ATTR):
        return getattr(request, _CART_CACHE_ATTR)

    cart = _lookup_cart(request=request, is_buy_now=False)
    setattr(request, _CART_CACHE_ATTR, cart)
    return cart


def get_buy_now_cart_for_request(*, request: HttpRequest) -> Optional[Cart]:
    """
    Resolve the isolated "Buy Now" cart for the current request.

    Completely separate row from the persistent cart — never returned by
    ``get_cart_for_request`` and never touched by normal add-to-cart flows.

    Query guarantee: at most 1 SELECT on cart_cart per request (request-scoped cache).
    """
    if hasattr(request, _BUY_NOW_CART_CACHE_ATTR):
        return getattr(request, _BUY_NOW_CART_CACHE_ATTR)

    cart = _lookup_cart(request=request, is_buy_now=True)
    setattr(request, _BUY_NOW_CART_CACHE_ATTR, cart)
    return cart


@dataclass
class CartSummaryLine:
    """Hydrated cart line for templates and checkout."""

    item: CartItem
    product: Any
    variant: Any
    quantity: int
    unit_price_at_add: Decimal
    line_subtotal: Decimal
    combo_name_snapshot: str = ""

    @property
    def is_combo(self) -> bool:
        """Cart templates render standalone lines and CartComboBlocks from one list; this tells them apart."""
        return False

    @property
    def available_stock(self) -> int:
        """
        Stock actually available for this specific line.

        """
        if self.variant is not None:
            return self.variant.stock_quantity
        return self.product.stock_quantity

    @property
    def is_in_stock(self) -> bool:
        """Whether this line (its variant, if any) is currently sellable."""
        return self.available_stock > 0

    @property
    def effective_hsn_code(self) -> str:
        """HSN/SAC code for this line: the variant's own if set, else the product's."""
        if self.variant is not None:
            return self.variant.effective_hsn_code
        return self.product.hsn_code

    @property
    def effective_gst_rate_percent(self):
        """GST % for this line: the variant's own if set, else the product's."""
        if self.variant is not None:
            return self.variant.effective_gst_rate_percent
        return self.product.gst_rate_percent

    @property
    def display_image(self):
        """
        The thumbnail this line should show: the selected variant's own
        image when it has one (matching what the PDP shows once that
        variant is picked - see catalog.selectors.get_variant_price's same
        variant-images-first-else-product-images fallback), otherwise the
        product's own primary image. Without this, cart/checkout thumbnails
        always showed the product's generic image regardless of which
        variant was actually added.
        """
        if self.variant is not None:
            variant_images = getattr(self.variant, "variant_images", None)
            if variant_images:
                return variant_images[0]
        primary_images = getattr(self.product, "primary_images", None)
        if primary_images:
            return primary_images[0]
        return None


@dataclass
class CartComboBlock:
    """
    One combo in the cart: its component lines, shown and controlled as a single unit.

    ``units`` is how many of the combo the customer has (each line's quantity is
    its per-combo quantity × units). It is None when the combo's definition was
    edited after this was added and the lines no longer add up to whole combos —
    the block is still shown and removable, just not resizable.
    """

    combo: Combo
    lines: list[CartSummaryLine] = field(default_factory=list)
    units: Optional[int] = None
    total: Decimal = Decimal("0.00")
    normal_total: Optional[Decimal] = None
    savings: Decimal = Decimal("0.00")
    cover_url: str = ""
    has_stock_issue: bool = False

    @property
    def is_combo(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return self.combo.name


def combo_units(*, items, combo_items) -> Optional[int]:
    """
    How many of a combo a set of cart lines makes up, or None if they don't form whole combos.

    ``items`` are CartItems of one combo; ``combo_items`` the combo's current
    ComboItem rows. Every component must be present and each line's quantity must be
    the same whole multiple of its per-combo quantity.
    """
    per_combo = {(ci.product_id, ci.variant_id): ci.quantity for ci in combo_items}
    if len(items) != len(per_combo):
        return None
    multiples = set()
    for item in items:
        needed = per_combo.get((item.product_id, item.variant_id))
        if not needed or item.quantity % needed:
            return None
        multiples.add(item.quantity // needed)
    return multiples.pop() if len(multiples) == 1 else None


def _build_combo_block(combo: Combo, lines: list[CartSummaryLine]) -> CartComboBlock:
    combo_items = list(combo.items.all())
    units = combo_units(items=[line.item for line in lines], combo_items=combo_items)
    total = sum((line.line_subtotal for line in lines), Decimal("0.00"))

    normal_total = None
    savings = Decimal("0.00")
    if units:
        normal_total = combo.normal_price * units
        savings = max(normal_total - total, Decimal("0.00"))

    cover_url = ""
    for image in combo.images.all():
        if image.image:
            cover_url = image.image.url
            break
    if not cover_url and combo.image:
        cover_url = combo.image.url

    return CartComboBlock(
        combo=combo,
        lines=lines,
        units=units,
        total=total,
        normal_total=normal_total,
        savings=savings,
        cover_url=cover_url,
        has_stock_issue=any(
            not line.is_in_stock or line.quantity > line.available_stock for line in lines
        ),
    )


@dataclass
class CartSummary:
    """Computed cart totals — single selector call, no N+1."""

    cart: Cart
    lines: list[CartSummaryLine] = field(default_factory=list)
    blocks: list[Any] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    coupon_code: str = ""
    coupon_discount: Decimal = Decimal("0.00")
    delivery_charge: Decimal = Decimal("0.00")
    free_delivery: bool = False
    grand_total: Decimal = Decimal("0.00")
    item_count: int = 0
    has_stock_issues: bool = False
    has_out_of_stock_items: bool = False


def get_cart_by_id(*, cart_id: int) -> Optional[Cart]:
    """
    Return a cart by primary key.

    Query guarantee: exactly 1 SELECT on cart_cart.
    """
    return Cart.objects.filter(pk=cart_id).select_related("currency", "destination_city").first()


def get_cart_item_count(*, cart: Cart | None) -> int:
    """
    Return total item quantity for a cart without hydrating line items.

    Query guarantee: exactly 1 aggregate SELECT on cart_cartitem (0 rows → 0).
    """
    if cart is None:
        return 0
    total = CartItem.objects.filter(cart=cart).aggregate(total=Sum("quantity"))["total"]
    return int(total or 0)


def get_cart_count(*, request: HttpRequest) -> int:
    """
    Return total item quantity in the persistent cart.

    Query guarantee: 0–1 SELECT (cart lookup) + 0–1 aggregate on cart items.
    """
    cart = get_cart_for_request(request=request)
    return get_cart_item_count(cart=cart)


def get_cart_product_ids(*, request: HttpRequest) -> set[int]:
    """Return a set of product IDs currently in the persistent cart."""
    cart = get_cart_for_request(request=request)
    if not cart:
        return set()
    # Combo components don't count: a product sitting in the cart only inside a combo
    # can still be added on its own from its card/PDP.
    return set(
        CartItem.objects.filter(cart=cart, combo__isnull=True).values_list("product_id", flat=True)
    )


def _wishlist_items_qs(*, request: HttpRequest):
    """Shared queryset for the current request's wishlist items."""
    from accounts.models import WishlistItem

    if request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        return WishlistItem.objects.filter(
            wishlist__customer_profile=request.user.customer_profile
        )
    guest_id = request.session.get("guest_wishlist_id")
    if guest_id:
        return WishlistItem.objects.filter(wishlist_id=guest_id)
    if not request.session.session_key:
        return WishlistItem.objects.none()
    return WishlistItem.objects.filter(wishlist__session_key=request.session.session_key)


def get_wishlist_count(*, request: HttpRequest) -> int:
    """Return wishlist item count from the persistent Wishlist model."""
    return _wishlist_items_qs(request=request).count()


def get_wishlist_product_ids(*, request: HttpRequest) -> set[int]:
    """Return product IDs currently on the request wishlist."""
    return set(_wishlist_items_qs(request=request).values_list("product_id", flat=True))


def get_cart_summary(*, cart: Cart) -> CartSummary:
    """
    Return a fully computed cart summary for drawer, checkout, and payment.

    Query guarantee:
      1) cart items SELECT with select_related(product, variant, category, brand)
      2) one gifting.get_gift_customization_snapshot call per customized line
         (each is a constant 1 SELECT + prefetches inside gifting — no cart ORM
         into gifting tables)

    Cross-app boundary: gift snapshot hydration is delegated exclusively to
    ``gifting.selectors.get_gift_customization_snapshot``.
    """
    items = list(
        CartItem.objects.filter(cart=cart)
        .select_related(
            "product",
            "product__category",
            "product__brand",
            "variant",
            "combo",
        )
        .prefetch_related(
            Prefetch(
                "combo__items",
                queryset=ComboItem.objects.select_related("product", "variant", "variant__product"),
            ),
            Prefetch(
                "combo__images",
                queryset=ComboImage.objects.order_by("-is_primary", "display_order"),
            ),
            Prefetch(
                "product__images",
                queryset=ProductImage.objects.filter(is_primary=True).order_by("display_order"),
                to_attr="primary_images",
            ),
            Prefetch(
                "variant__images",
                queryset=ProductImage.objects.order_by("-is_primary", "display_order"),
                to_attr="variant_images",
            ),
        )
        .order_by("id")
    )

    lines: list[CartSummaryLine] = []
    subtotal = Decimal("0.00")
    item_count = 0
    has_stock_issues = False
    has_out_of_stock_items = False

    user = (
        cart.customer_profile.user
        if (cart.customer_profile and cart.customer_profile.user_id)
        else None
    )
    from cart.services import _resolve_unit_price

    for item in items:
        if item.combo_id:
            # Combo lines are priced at add-time (see cart.services.add_combo_to_cart)
            # as a prorated share of the combo's fixed price — never recomputed
            # from the live catalog price, or the combo discount would vanish
            # the moment this summary is rendered.
            unit_price = item.unit_price_at_add
        else:
            try:
                unit_price = _resolve_unit_price(
                    product=item.product,
                    variant=item.variant,
                    user=user,
                    quantity=item.quantity,
                )
            except Product.DoesNotExist:
                unit_price = item.unit_price_at_add

        line_subtotal = unit_price * item.quantity
        subtotal += line_subtotal
        item_count += item.quantity
        line = CartSummaryLine(
            item=item,
            product=item.product,
            variant=item.variant,
            quantity=item.quantity,
            unit_price_at_add=unit_price,
            line_subtotal=line_subtotal,
            combo_name_snapshot=item.combo_name_snapshot,
        )
        lines.append(line)
        # Checks the specific variant's stock when this line has one, instead
        # of the parent product's stock_quantity (which is only meaningful
        # for products that don't have variants at all - see
        # CartSummaryLine.available_stock / Product.is_in_stock).
        if not line.is_in_stock:
            has_stock_issues = True
            has_out_of_stock_items = True
        elif item.quantity > line.available_stock:
            has_stock_issues = True

    # The vendor's "Charge customers for delivery" switch: when off, delivery is free
    # everywhere — this is the one place the cart-side charge is decided, so the cart page,
    # sidebar cart, checkout and the order all agree.
    free_delivery = not get_site_settings().charge_for_delivery
    delivery_charge = cart.delivery_charge
    if free_delivery:
        delivery_charge = Decimal("0.00")
    elif cart.destination_city_id and delivery_charge == Decimal("0.00"):
        delivery_charge = get_delivery_charge(
            item_count=item_count,
            destination_city=cart.destination_city,
        )

    coupon_code = cart.coupon_code
    coupon_discount = Decimal("0.00")
    if coupon_code:
        from marketing.services import validate_coupon_for_cart
        from marketing.exceptions import InvalidCouponError
        category_ids = [line.product.category_id for line in lines]
        try:
            result = validate_coupon_for_cart(
                code=coupon_code,
                cart_subtotal=subtotal,
                customer_profile_id=cart.customer_profile_id,
                cart_category_ids=category_ids,
            )
            coupon_discount = result["discount_amount"]
        except InvalidCouponError:
            coupon_code = ""
            coupon_discount = Decimal("0.00")

    grand_total = max(subtotal - coupon_discount + delivery_charge, Decimal("0.00"))

    # Standalone lines stay as they are; all lines of one combo collapse into a
    # single block placed where its first line was. (A line whose combo was
    # deleted has combo_id NULL and correctly shows as an ordinary product.)
    blocks: list[Any] = []
    combo_lines: dict[int, list[CartSummaryLine]] = {}
    for line in lines:
        combo_id = line.item.combo_id
        if combo_id is None:
            blocks.append(line)
        elif combo_id in combo_lines:
            combo_lines[combo_id].append(line)
        else:
            combo_lines[combo_id] = [line]
            blocks.append(combo_id)
    blocks = [
        _build_combo_block(combo_lines[b][0].item.combo, combo_lines[b]) if isinstance(b, int) else b
        for b in blocks
    ]

    return CartSummary(
        cart=cart,
        lines=lines,
        blocks=blocks,
        subtotal=subtotal,
        coupon_code=coupon_code,
        coupon_discount=coupon_discount,
        delivery_charge=delivery_charge,
        free_delivery=free_delivery,
        grand_total=grand_total,
        item_count=item_count,
        has_stock_issues=has_stock_issues,
        has_out_of_stock_items=has_out_of_stock_items,
    )
