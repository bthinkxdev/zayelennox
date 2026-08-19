"""HTTP views for the checkout app."""

from __future__ import annotations

import re

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.selectors import get_address_by_id, get_saved_addresses
from cart.selectors import get_cart_for_request, get_cart_summary
from cart.services import get_or_create_buy_now_cart, get_or_create_cart
from checkout.forms import CheckoutAddressForm, CheckoutPaymentForm
from checkout.selectors import get_checkout_session_by_id
from checkout.services import create_checkout_session, place_order, update_checkout_session

from payments.registry import PAYMENT_GATEWAYS
from payments.services import process_payment

# Indian mobile numbers: 10 digits, first digit 6-9 (no STD/country code).
INDIA_PHONE_RE = re.compile(r'^[6-9]\d{9}$')
PINCODE_RE = re.compile(r'^[1-9][0-9]{5}$')
ONLY_DIGITS_RE = re.compile(r'^\d+$')
# Requires at least one letter — rejects strings that are only digits and
# strings that are only special characters/punctuation (e.g. "123", "###").
HAS_LETTER_RE = re.compile(r'[A-Za-z]')


def _validate_delivery_fields(
    *,
    name: str,
    phone: str,
    address_line1: str,
    city_name: str,
    state_name: str,
    pincode: str,
    email: str | None = None,
    require_email: bool = False,
) -> dict[str, list[str]]:
    """
    Shared delivery-detail validation for checkout (guest, authenticated new
    address, and editing an existing saved address).

    """
    errors: dict[str, list[str]] = {}

    name = (name or "").strip()
    if not name:
        errors["guest_name"] = ["Name is required."]
    elif not HAS_LETTER_RE.search(name):
        errors["guest_name"] = ["Name must contain letters."]

    if require_email:
        email = (email or "").strip()
        if not email:
            errors["guest_email"] = ["Email is required."]
        else:
            try:
                validate_email(email)
            except ValidationError:
                errors["guest_email"] = ["Enter a valid email address."]

    phone = (phone or "").strip()
    if not phone:
        errors["guest_phone"] = ["Phone is required."]
    elif not ONLY_DIGITS_RE.match(phone):
        errors["guest_phone"] = ["Phone number can only contain numbers."]
    elif not INDIA_PHONE_RE.match(phone):
        errors["guest_phone"] = ["Enter a valid 10-digit Indian mobile number (must start with 6-9)."]

    address_line1 = (address_line1 or "").strip()
    if not address_line1:
        errors["guest_address_line1"] = ["Address Line 1 is required."]
    elif not HAS_LETTER_RE.search(address_line1):
        errors["guest_address_line1"] = ["Address Line 1 must contain letters."]

    city_name = (city_name or "").strip()
    if not city_name:
        errors["guest_city_name"] = ["City is required."]
    elif not HAS_LETTER_RE.search(city_name):
        errors["guest_city_name"] = ["City must contain letters."]

    state_name = (state_name or "").strip()
    if not state_name:
        errors["guest_state_name"] = ["State is required."]
    elif not HAS_LETTER_RE.search(state_name):
        errors["guest_state_name"] = ["State must contain letters."]

    pincode = (pincode or "").strip()
    if not pincode:
        errors["guest_pincode"] = ["Pincode is required."]
    elif not PINCODE_RE.match(pincode):
        errors["guest_pincode"] = ["Enter a valid 6-digit pincode."]

    return errors


def _is_buy_now_request(request: HttpRequest) -> bool:
    """True when the current checkout request is for the isolated Buy Now cart."""
    if request.method == "GET":
        return request.GET.get("buy_now") == "1"
    return request.POST.get("buy_now") == "1"


def _resolve_checkout_cart(request: HttpRequest):
    """
    Resolve which cart this checkout request should operate on.

    Returns (cart, buy_now_mode). Buy Now checkout always resolves to its own
    isolated single-item cart — never the customer's persistent cart, and
    never affected by what's already sitting in it.
    """
    if _is_buy_now_request(request):
        return get_or_create_buy_now_cart(request=request), True
    return get_or_create_cart(request=request), False


def _checkout_url(*, buy_now_mode: bool) -> str:
    url = reverse("checkout:checkout")
    return f"{url}?buy_now=1" if buy_now_mode else url


@require_GET
def checkout_view(request: HttpRequest) -> HttpResponse:
    """Multi-step checkout page with gift Order Preview partial."""
    cart, buy_now_mode = _resolve_checkout_cart(request)
    summary = get_cart_summary(cart=cart)
    if not summary.lines:
        #do not redirect,render the empty state in checkout.html
        pass

    if request.user.is_authenticated:
        from accounts.services import ensure_customer_profile_for_user
        profile = ensure_customer_profile_for_user(user=request.user)
    else:
        profile = None

    session = create_checkout_session(
        cart=cart,
        customer_profile=profile,
        session_key=request.session.session_key or "",
    )


    addresses = []
    if profile:
        # Show every saved address as a choice, not just the default/first one
        # (get_saved_addresses already orders default-first, then newest).
        addresses = get_saved_addresses(customer_profile=profile)["results"]

    selected_gateway_key = None
    if session.order:
        last_tx = session.order.payment_transactions.last()
        if last_tx:
            selected_gateway_key = last_tx.gateway_key

    from payments.adapters.concrete import _get_razorpay_credentials
    razorpay_key, razorpay_secret = _get_razorpay_credentials()
    
    available_gateways = {}
    for key, adapter in PAYMENT_GATEWAYS.items():
        if key.startswith("razorpay") and (not razorpay_key or not razorpay_secret):
            continue
        available_gateways[key] = adapter

    from marketing.selectors import has_any_active_coupons
    return render(
        request,
        "checkout/checkout.html",
        {
            "cart": cart,
            "summary": summary,
            "checkout_session": session,
            "addresses": addresses,
            "payment_gateways": available_gateways,
            "selected_gateway_key": selected_gateway_key,
            "has_active_coupons": has_any_active_coupons(),
            "buy_now_mode": buy_now_mode,
        },
    )


@require_http_methods(["POST"])
def checkout_place_order_view(request: HttpRequest) -> HttpResponse:
    """Place order and process payment in one HTMX step."""
    form = CheckoutPaymentForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": form.errors},
            status=200,
        )

    buy_now_mode = _is_buy_now_request(request)
    if buy_now_mode:
        from cart.selectors import get_buy_now_cart_for_request
        cart = get_buy_now_cart_for_request(request=request)
    else:
        cart = get_cart_for_request(request=request)
    if cart is None:
        raise Http404("Cart not found.")

    if request.user.is_authenticated:
        from accounts.services import ensure_customer_profile_for_user
        profile = ensure_customer_profile_for_user(user=request.user)
    else:
        profile = None

    session = create_checkout_session(cart=cart, customer_profile=profile, session_key=request.session.session_key or "")
    
    address = None
    address_form = CheckoutAddressForm(request.POST)
    if address_form.is_valid() and address_form.cleaned_data.get("address_id") and profile:
        address = get_address_by_id(
            address_id=address_form.cleaned_data["address_id"],
            customer_profile=profile,
        )
        if address:
            update_checkout_session(checkout_session=session, address=address)

    if not address:
        if not request.user.is_authenticated:
            guest_name = request.POST.get("guest_name", "").strip()
            guest_email = request.POST.get("guest_email", "").strip()
            guest_phone = request.POST.get("guest_phone", "").strip()
            guest_address_line1 = request.POST.get("guest_address_line1", "").strip()
            guest_address_line2 = request.POST.get("guest_address_line2", "").strip()
            guest_city_name = request.POST.get("guest_city_name", "").strip()
            guest_state_name = request.POST.get("guest_state_name", "").strip()
            guest_pincode = request.POST.get("guest_pincode", "").strip()

            errors = _validate_delivery_fields(
                name=guest_name,
                phone=guest_phone,
                address_line1=guest_address_line1,
                city_name=guest_city_name,
                state_name=guest_state_name,
                pincode=guest_pincode,
                email=guest_email,
                require_email=True,
            )

            if errors:
                return render(
                    request,
                    "checkout/partials/errors.html",
                    {"errors": errors},
                    status=200,
                )

            from accounts.services import login_or_create_customer_by_email
            from accounts.models import Address

            profile = login_or_create_customer_by_email(email=guest_email, name=guest_name)
            if guest_phone:
                profile.phone = guest_phone
                profile.save(update_fields=["phone", "updated_at"])

            address = Address.objects.filter(
                customer_profile=profile,
                line1=guest_address_line1,
                line2=guest_address_line2,
                pincode=guest_pincode,
            ).first()
            if not address:
                address = Address.objects.create(
                    customer_profile=profile,
                    line1=guest_address_line1,
                    line2=guest_address_line2,
                    city_name=guest_city_name,
                    state_name=guest_state_name,
                    pincode=guest_pincode,
                    label="Delivery Address"
                )
            else:
                address.city_name = guest_city_name
                address.state_name = guest_state_name
                address.save(update_fields=["city_name", "state_name", "updated_at"])

            if profile.default_address is None:
                from accounts.services import set_default_address
                set_default_address(customer_profile=profile, address_id=address.pk)
                
            update_checkout_session(checkout_session=session, address=address)
            
            #update session customer profile
            session.customer_profile = profile
            session.save(update_fields=["customer_profile", "updated_at"])
        else:
            guest_name = request.POST.get("guest_name", "").strip()
            guest_phone = request.POST.get("guest_phone", "").strip()
            guest_address_line1 = request.POST.get("guest_address_line1", "").strip()
            guest_address_line2 = request.POST.get("guest_address_line2", "").strip()
            guest_city_name = request.POST.get("guest_city_name", "").strip()
            guest_state_name = request.POST.get("guest_state_name", "").strip()
            guest_pincode = request.POST.get("guest_pincode", "").strip()

            errors = _validate_delivery_fields(
                name=guest_name,
                phone=guest_phone,
                address_line1=guest_address_line1,
                city_name=guest_city_name,
                state_name=guest_state_name,
                pincode=guest_pincode,
            )

            if errors:
                return render(
                    request,
                    "checkout/partials/errors.html",
                    {"errors": errors},
                    status=200,
                )

            from accounts.models import Address

            if guest_name and request.user.first_name != guest_name:
                request.user.first_name = guest_name
                request.user.save(update_fields=["first_name"])
            if guest_phone and profile.phone != guest_phone:
                profile.phone = guest_phone
                profile.save(update_fields=["phone", "updated_at"])

            address = Address.objects.filter(
                customer_profile=profile,
                line1=guest_address_line1,
                line2=guest_address_line2,
                pincode=guest_pincode,
            ).first()
            if not address:
                address = Address.objects.create(
                    customer_profile=profile,
                    line1=guest_address_line1,
                    line2=guest_address_line2,
                    city_name=guest_city_name,
                    state_name=guest_state_name,
                    pincode=guest_pincode,
                    label="Delivery Address"
                )
            else:
                address.city_name = guest_city_name
                address.state_name = guest_state_name
                address.save(update_fields=["city_name", "state_name", "updated_at"])

            if profile.default_address is None:
                from accounts.services import set_default_address
                set_default_address(customer_profile=profile, address_id=address.pk)

            update_checkout_session(checkout_session=session, address=address)

    from cart.selectors import get_cart_summary
    summary = get_cart_summary(cart=cart)
    if summary.has_stock_issues:
        from django.utils.translation import gettext as _
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": {"__all__": [_("Some items in your cart are out of stock. Please remove them to proceed.")]}},
            status=200,
        )

    shipping_charge_override = None
    delivery_pincode = session.address.pincode if session.address_id else None
    from shipping.views import SESSION_KEY as SHIPROCKET_SESSION_KEY

    stored_quote = request.session.get(SHIPROCKET_SESSION_KEY)
    if delivery_pincode and stored_quote and stored_quote.get("pincode") == delivery_pincode:
        from decimal import Decimal

        try:
            shipping_charge_override = Decimal(str(stored_quote.get("shipping_charge", 0)))
        except Exception:
            shipping_charge_override = None

    try:
        from catalog.exceptions import InsufficientStockError
        order = place_order(
            checkout_session_id=session.pk,
            idempotency_key=form.cleaned_data["idempotency_key"],
            customer_profile=profile,
            shipping_charge_override=shipping_charge_override,
        )
    except InsufficientStockError as exc:
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": {"__all__": [str(exc)]}},
            status=200,
        )

    payment_data = {}

    gateway_key = form.cleaned_data["gateway_key"]
    process_payment(
        order=order,
        gateway_key=gateway_key,
        payment_data=payment_data,
    )

    if gateway_key.startswith("razorpay"):
        pay_url = reverse("checkout:razorpay-pay", kwargs={"order_id": order.pk})
        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response["HX-Redirect"] = pay_url
            return response
        return redirect(pay_url)

    confirmation_url = reverse("checkout:confirmation", kwargs={"order_id": order.pk})
    if request.headers.get("HX-Request"):
        response = HttpResponse()
        response["HX-Redirect"] = confirmation_url
        return response
    return redirect(confirmation_url)


@login_required
@require_POST
def checkout_address_update_view(request: HttpRequest, address_id: int) -> HttpResponse:
    """
    Update an existing saved address's delivery details from the checkout
    page's "Edit" modal (AJAX, JSON in/out).

    """
    from accounts.services import ensure_customer_profile_for_user

    profile = ensure_customer_profile_for_user(user=request.user)
    address = get_address_by_id(address_id=address_id, customer_profile=profile)
    if not address:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["Address not found."]}},
            status=404,
        )

    data = request.POST
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    address_line1 = data.get("address_line1", "").strip()
    address_line2 = data.get("address_line2", "").strip()
    city_name = data.get("city_name", "").strip()
    state_name = data.get("state_name", "").strip()
    pincode = data.get("pincode", "").strip()

    errors = _validate_delivery_fields(
        name=name,
        phone=phone,
        address_line1=address_line1,
        city_name=city_name,
        state_name=state_name,
        pincode=pincode,
    )
    if errors:
        return JsonResponse({"success": False, "errors": errors}, status=400)

    if name and request.user.first_name != name:
        request.user.first_name = name
        request.user.save(update_fields=["first_name"])
    if phone and profile.phone != phone:
        profile.phone = phone
        profile.save(update_fields=["phone", "updated_at"])

    address.line1 = address_line1
    address.line2 = address_line2
    address.city_name = city_name
    address.state_name = state_name
    address.pincode = pincode
    address.save(update_fields=["line1", "line2", "city_name", "state_name", "pincode", "updated_at"])

    display_city = address.city_name or (address.city.name if address.city_id else "")
    display = f"{address.label} — {address.line1}, {display_city}"
    if address.pincode:
        display += f" - {address.pincode}"

    return JsonResponse(
        {
            "success": True,
            "address": {
                "id": address.pk,
                "label": address.label,
                "line1": address.line1,
                "line2": address.line2,
                "city_name": address.city_name,
                "state_name": address.state_name,
                "pincode": address.pincode,
                "display": display,
            },
            "name": name,
            "phone": phone,
        }
    )


@require_GET
def checkout_confirmation_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Separate order confirmation / success page."""
    from orders.models import Order
    from django.shortcuts import get_object_or_404
    order = get_object_or_404(Order, pk=order_id)
    return render(
        request,
        "checkout/confirmation_page.html",
        {
            "order": order,
        },
    )


@require_GET
def razorpay_pay_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Render Razorpay checkout payment page."""
    from orders.models import Order
    from payments.models import PaymentTransaction
    from payments.adapters.concrete import _get_razorpay_credentials
    from django.shortcuts import get_object_or_404

    order = get_object_or_404(Order, pk=order_id)
    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key__startswith="razorpay").last()
    key_id, _ = _get_razorpay_credentials()

    customer_name = ""
    customer_email = ""
    customer_phone = ""
    if order.customer_profile:
        customer_name = f"{order.customer_profile.user.first_name} {order.customer_profile.user.last_name}".strip() or order.customer_profile.user.username
        customer_email = order.customer_profile.user.email
        customer_phone = order.customer_profile.phone
    elif order.delivery_address_snapshot:
        customer_name = order.delivery_address_snapshot.get("recipient_name", "")
        customer_email = order.delivery_address_snapshot.get("email", "")
        customer_phone = order.delivery_address_snapshot.get("phone", "")

    amount_in_paise = int(order.total_amount * 100)
    from core.selectors import get_default_currency
    default_curr = get_default_currency()
    currency_code = order.currency.code if order.currency else (default_curr.code if default_curr else "INR")
    razorpay_order_id = payment_tx.external_intent_id if payment_tx else f"rzp_order_{order.pk}"

    #determine prefill method based on gateway key
    prefill_method = ""
    payment_method_name = "Razorpay"
    if payment_tx and payment_tx.gateway_key:
        if payment_tx.gateway_key == "razorpay_upi":
            prefill_method = "upi"
            payment_method_name = "UPI"
        elif payment_tx.gateway_key == "razorpay_card":
            prefill_method = "card"
            payment_method_name = "Credit/Debit Card"
        elif payment_tx.gateway_key == "razorpay_netbanking":
            prefill_method = "netbanking"
            payment_method_name = "Net Banking"
        elif payment_tx.gateway_key == "razorpay_wallet":
            prefill_method = "wallet"
            payment_method_name = "Wallet"

    #store order_id in session so the callback can retrieve it
    request.session["razorpay_order_pk"] = order.pk

    #build absolute callback URL for Razorpay redirect
    callback_url = request.build_absolute_uri(reverse("checkout:razorpay-callback"))
    order_was_buy_now = bool(order.cart_id and getattr(order.cart, "is_buy_now", False))
    cancel_url = request.build_absolute_uri(_checkout_url(buy_now_mode=order_was_buy_now))

    return render(
        request,
        "checkout/razorpay_pay.html",
        {
            "order": order,
            "razorpay_key_id": key_id or "rzp_test_mock",
            "razorpay_order_id": razorpay_order_id,
            "amount_in_paise": amount_in_paise,
            "currency_code": currency_code,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
            "callback_url": callback_url,
            "cancel_url": cancel_url,
            "prefill_method": prefill_method,
            "payment_method_name": payment_method_name,
        },
    )


from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
@require_http_methods(["POST"])
def razorpay_callback_view(request: HttpRequest) -> HttpResponse:
    """
    Handle POST callback from Razorpay after payment.

    Razorpay redirects the full browser here with razorpay_payment_id,
    razorpay_order_id, and razorpay_signature as POST parameters.
    """
    from payments.models import PaymentTransaction
    from payments.adapters.concrete import RazorpayAdapter
    from payments.services import confirm_payment_success, confirm_payment_failed
    from django.shortcuts import get_object_or_404
    from orders.models import Order

    razorpay_payment_id = request.POST.get("razorpay_payment_id", "")
    razorpay_order_id = request.POST.get("razorpay_order_id", "")
    razorpay_signature = request.POST.get("razorpay_signature", "")

    #try order_id from POST (JS form submit) or session (Razorpay redirect)
    order_id = request.POST.get("order_id") or request.session.get("razorpay_order_pk")

    if not order_id:
        #fallback: look up order via Razorpay order ID stored in PaymentTransaction
        payment_tx = PaymentTransaction.objects.filter(
            external_intent_id=razorpay_order_id,
            gateway_key__startswith="razorpay",
        ).last()
        if payment_tx:
            order_id = payment_tx.order_id
        else:
            return redirect("checkout:checkout")

    order = get_object_or_404(Order, pk=order_id)
    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key__startswith="razorpay").last()

    #clean up session
    request.session.pop("razorpay_order_pk", None)

    adapter = RazorpayAdapter()
    is_valid = adapter.verify_payment_signature(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    )

    if is_valid and payment_tx:
        adapter.capture_payment(
            razorpay_payment_id=razorpay_payment_id,
            amount=payment_tx.amount,
            currency=payment_tx.currency.code if payment_tx.currency else (default_curr.code if default_curr else "INR"),
        )
        payment_tx.external_transaction_id = razorpay_payment_id
        payment_tx.save(update_fields=["external_transaction_id", "updated_at"])
        confirm_payment_success(payment_transaction=payment_tx)
        return redirect("checkout:confirmation", order_id=order.pk)
    else:
        if payment_tx:
            confirm_payment_failed(payment_transaction=payment_tx)
        order_was_buy_now = bool(order.cart_id and getattr(order.cart, "is_buy_now", False))
        return redirect(_checkout_url(buy_now_mode=order_was_buy_now))


@require_POST
def checkout_coupon_apply_view(request: HttpRequest) -> HttpResponse:
    """Validate and apply a coupon code from checkout."""
    from cart.forms import CartCouponForm
    from cart.services import apply_coupon
    from marketing.exceptions import InvalidCouponError
    from django.contrib import messages
    from django.utils.translation import gettext as _

    buy_now_mode = _is_buy_now_request(request)

    form = CartCouponForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Enter a valid coupon code."))
        return redirect(_checkout_url(buy_now_mode=buy_now_mode))

    if buy_now_mode:
        from cart.selectors import get_buy_now_cart_for_request
        cart = get_buy_now_cart_for_request(request=request)
    else:
        cart = get_cart_for_request(request=request)
    if cart is None:
        raise Http404("Cart not found.")

    try:
        apply_coupon(cart=cart, code=form.cleaned_data["code"])
        messages.success(request, _("Coupon applied successfully!"))
    except InvalidCouponError as exc:
        messages.error(request, str(exc))

    return redirect(_checkout_url(buy_now_mode=buy_now_mode))


@require_POST
def checkout_coupon_remove_view(request: HttpRequest) -> HttpResponse:
    """Remove any applied coupon from the cart from checkout."""
    from cart.services import remove_coupon
    from django.contrib import messages
    from django.utils.translation import gettext as _

    buy_now_mode = _is_buy_now_request(request)

    if buy_now_mode:
        from cart.selectors import get_buy_now_cart_for_request
        cart = get_buy_now_cart_for_request(request=request)
    else:
        cart = get_cart_for_request(request=request)
    if cart:
        remove_coupon(cart=cart)
        messages.success(request, _("Coupon removed."))
    return redirect(_checkout_url(buy_now_mode=buy_now_mode))
