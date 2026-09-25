"""HTTP views for the catalog app; thin request parsing delegating to selectors/services."""

from __future__ import annotations

import json

from django.core import signing
from django.db import IntegrityError
from django.db.models import Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache
from django.contrib import messages

from catalog.models import Product, Review
from catalog.forms import ReviewSubmissionForm
from catalog.services import has_delivered_purchase, submit_review, verify_review_invite_token

from catalog.selectors import (
    get_active_combos,
    get_category_by_slug,
    get_combo_by_slug,
    get_plp_filter_options,
    get_plp_products,
    get_product_detail,
    get_related_products,
    get_search_suggestions,
    get_variant_price,
    record_product_view,
)
from core.seo import build_plp_canonical_url, build_product_json_ld, resolve_meta_title, seo_context
from delivery.selectors import (
    get_active_cities,
    get_city_by_slug,
    get_earliest_delivery_estimate,
)


def _parse_plp_filters(request: HttpRequest) -> dict:
    """Parse shareable PLP filter query params into a selector filter dict."""
    filters: dict = {}
    category_id = request.GET.get("category")
    subcategory_id = request.GET.get("subcategory")
    if subcategory_id:
        filters["category_id"] = int(subcategory_id)
        filters["subcategory_id"] = int(subcategory_id)
        if category_id:
            filters["parent_category_id"] = int(category_id)
    elif category_id:
        filters["category_id"] = int(category_id)

    if occasion_id := request.GET.get("occasion"):
        filters["occasion_id"] = int(occasion_id)
    if brand_id := request.GET.get("brand"):
        filters["brand_id"] = int(brand_id)
    if recipient_id := request.GET.get("recipient"):
        filters["recipient_id"] = int(recipient_id)
    if color := request.GET.get("color"):
        filters["color"] = color
    if request.GET.get("featured") == "1":
        filters["featured"] = True
    if request.GET.get("bestseller") == "1":
        filters["bestseller"] = True
    if request.GET.get("new_arrival") == "1":
        filters["new_arrival"] = True
    if request.GET.get("in_stock") == "1":
        filters["in_stock"] = True
    if min_price := request.GET.get("min_price"):
        filters["min_price"] = min_price
    if max_price := request.GET.get("max_price"):
        filters["max_price"] = max_price
    return filters


@require_GET
@never_cache
def plp_view(request: HttpRequest, category_slug: str | None = None) -> HttpResponse:
    """
    Product listing page with HTMX partial support for the product grid.

    @never_cache prevents the browser from restoring this page from disk
    cache / back-forward cache with a stale "Add to Cart"/"View Cart"
    state on the product cards. See pdp_view below for the full rationale.
    """
    filters = _parse_plp_filters(request)
    category = None
    if category_slug:
        category = get_category_by_slug(slug=category_slug)
        if category is None:
            raise Http404("Category not found")

        if not filters.get("subcategory_id") and not filters.get("category_id"):
            filters["category_id"] = category.pk

    resolved_cat = category
    if not resolved_cat and (cat_id := filters.get("category_id")):
        from catalog.models import Category

        resolved_cat = Category.objects.filter(pk=cat_id, is_active=True).first()

    subcategories = []
    if resolved_cat:
        if resolved_cat.parent_id:
            subcategories = list(resolved_cat.parent.children.filter(is_active=True))
            filters["subcategory_id"] = resolved_cat.pk
            filters["parent_category_id"] = resolved_cat.parent_id
        else:
            subcategories = list(resolved_cat.children.filter(is_active=True))
            filters["parent_category_id"] = resolved_cat.pk

    sort = request.GET.get("sort", "newest")
    page = int(request.GET.get("page", 1))
    plp_data = get_plp_products(filters=filters, sort=sort, page=page, user=request.user)
    filter_options = get_plp_filter_options()

    active_cat = resolved_cat if resolved_cat else None
    title = (
        resolve_meta_title(obj=active_cat, fallback="Shop All | ZAYE LENNOX")
        if active_cat
        else "Shop All | ZAYE LENNOX"
    )
    description = (
        f"Browse {active_cat.name} — Hair Care, Skin Care & Body Care, and more in Kerala."
        if active_cat
        else "Browse hair care, skin care, and body care products available in Kerala."
    )

    context = seo_context(
        request=request,
        obj=active_cat,
        title=f"{title} | ZAYE LENNOX",
        description=description,
        canonical_url=build_plp_canonical_url(request=request, category_slug=category_slug),
    )
    context.update(
        {
            "plp": plp_data,
            "filters": filters,
            "sort": sort,
            "categories": filter_options["categories"],
            "brands": filter_options["brands"],
            "subcategories": subcategories,
            "subcategories_map": filter_options.get("subcategories_map", {}),
            "active_category": active_cat,
        }
    )

    if request.headers.get("HX-Request"):
        # product_grid_htmx.html includes the grid partial and also OOB-swaps
        # #plp-toolbar-copy (title + result count), which otherwise sit
        # outside #product-grid and never got the memo. See templates/catalog/plp.html.
        return render(request, "catalog/partials/product_grid_htmx.html", context)
    return render(request, "catalog/plp.html", context)


@require_GET
@never_cache
def pdp_view(request: HttpRequest, slug: str) -> HttpResponse:
    """
    Product detail page with gallery, variants, reviews, and delivery estimate.

    @never_cache sends Cache-Control: no-store — without it, browsers may
    serve this page from disk cache or restore it from the back/forward
    cache on a browser-back navigation, showing a stale "View Cart"/
    "Add to Cart" state if the cart changed on another page in between.
    no-store also makes the page ineligible for bfcache in the first place,
    so every back navigation here is guaranteed to hit the server fresh.
    """
    product = get_product_detail(slug=slug)
    if product is None:
        raise Http404("Product not found")

    viewer_key = str(request.session.session_key or request.user.pk or "anon")
    record_product_view(viewer_key=viewer_key, product_id=product.pk)

    city_slug = request.GET.get("city", "ernakulam")
    destination_city = get_city_by_slug(slug=city_slug)
    if not destination_city:
        active_cities = get_active_cities()
        destination_city = active_cities[0] if active_cities else None
    delivery_estimate = None
    if destination_city:
        delivery_estimate = get_earliest_delivery_estimate(
            product=product,
            destination_city=destination_city,
        )


    from core.services import get_site_settings

    site_settings = get_site_settings()

    from cart.models import CartItem
    from cart.selectors import get_cart_for_request

    cart = get_cart_for_request(request=request)
    requested_variant_id = request.GET.get("variant_id")

    # Once a product has variants, it's only sellable through one of them
    
    variant_list = list(getattr(product, "variant_list", None) or [])
    resolved_variant_id: int | None = None
    if requested_variant_id and requested_variant_id.isdigit():
        candidate_id = int(requested_variant_id)
        if any(v.pk == candidate_id for v in variant_list):
            resolved_variant_id = candidate_id

    if resolved_variant_id is None and variant_list:
        in_stock_variants = [v for v in variant_list if v.stock_quantity > 0]
        variant_pool = in_stock_variants or variant_list
        default_variant = min(variant_pool, key=lambda v: v.price_delta)
        resolved_variant_id = default_variant.pk

    if resolved_variant_id is not None:
        cart_item = (
            CartItem.objects.filter(
                cart=cart, product=product, variant_id=resolved_variant_id, combo__isnull=True
            ).first()
            if cart
            else None
        )
    else:
        cart_item = (
            CartItem.objects.filter(
                cart=cart, product=product, variant__isnull=True, combo__isnull=True
            ).first()
            if cart
            else None
        )
    is_in_cart = cart_item is not None

    quantity = cart_item.quantity if cart_item else 1
    price_data = get_variant_price(
        product_id=product.pk, variant_id=resolved_variant_id, user=request.user, quantity=quantity
    )
    resolved_stock = int(price_data.get("stock_quantity", product.stock_quantity))

    reviews = getattr(product, "approved_reviews", [])
    review_count = len(reviews)
    average_rating = None
    if review_count:
        average_rating = sum(r.rating for r in reviews) / review_count

    from accounts.models import WishlistItem
    from accounts.subscription_services import get_or_create_wishlist

    wishlist = get_or_create_wishlist(request=request)
    is_in_wishlist = WishlistItem.objects.filter(wishlist=wishlist, product_id=product.pk).exists()


    has_delivered_order = False
    if request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        has_delivered_order = has_delivered_purchase(
            customer_profile=request.user.customer_profile, product=product
        )

    review_token = ""
    review_order_id = None
    raw_token = request.GET.get("review_token", "")
    if raw_token:
        from orders.models import Order, OrderItem, OrderStatus

        try:
            payload = verify_review_invite_token(token=raw_token)
        except signing.BadSignature:
            payload = None
        if payload and payload.get("product_id") == product.pk:
            order_exists = Order.objects.filter(
                pk=payload.get("order_id"), order_status=OrderStatus.DELIVERED
            ).exists()
            item_exists = order_exists and OrderItem.objects.filter(
                order_id=payload.get("order_id"), product=product
            ).exists()
            if item_exists:
                review_token = raw_token
                review_order_id = payload.get("order_id")

    already_reviewed = False
    if review_order_id is not None:
        already_reviewed = Review.objects.filter(order_id=review_order_id, product=product).exists()
    elif has_delivered_order:
        already_reviewed = Review.objects.filter(
            order__customer_profile=request.user.customer_profile, product=product
        ).exists()

    can_review = has_delivered_order or bool(review_token)

    context = seo_context(
        request=request,
        obj=product,
        title=f"{product.name} | ZAYE LENNOX",
        description=f"{product.name} — Hair Care, Skin Care & Body Care from ZAYE LENNOX, Kerala.",
    )
    context.update(
        {
            "product": product,
            "price_data": price_data,
            "delivery_estimate": delivery_estimate,
            "cities": get_active_cities(),
            "whatsapp_number": site_settings.whatsapp_number,
            "is_in_cart": is_in_cart,
            "cart_item": cart_item,
            "selected_variant_id": resolved_variant_id or "",
            "resolved_stock": resolved_stock,
            "is_in_wishlist": is_in_wishlist,
            "related_products": get_related_products(product=product, user=request.user),
            "has_delivered_order": has_delivered_order,
            "can_review": can_review,
            "already_reviewed": already_reviewed,
            "review_token": review_token,
            "product_json_ld": json.dumps(
                build_product_json_ld(
                    product=product,
                    price=price_data["price"],
                    request=request,
                    average_rating=average_rating,
                    review_count=review_count,
                )
            ),
        }
    )
    return render(request, "catalog/pdp.html", context)


@require_GET
def search_suggestions_view(request: HttpRequest) -> HttpResponse:
    """HTMX live search suggestions partial."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        response = render(
            request,
            "catalog/partials/search_suggestions.html",
            {
                "products": [],
                "brands": [],
                "categories": [],
                "equipment_types": [],
                "query": "",
            },
        )
        response.content = response.content.strip()
        return response
    suggestions = get_search_suggestions(query=query)
    context = {
        "products": suggestions.get("products", []),
        "brands": suggestions.get("brands", []),
        "categories": suggestions.get("categories", []),
        "equipment_types": suggestions.get("equipment_types", []),
        "query": query,
    }
    response = render(
        request,
        "catalog/partials/search_suggestions.html",
        context,
    )
    response.content = response.content.strip()
    return response


@require_GET
def variant_price_view(request: HttpRequest, product_id: int) -> JsonResponse:
    """JSON endpoint for variant price updates on PDP."""
    variant_id = request.GET.get("variant_id")
    quantity_str = request.GET.get("quantity", "1")
    try:
        quantity = int(quantity_str)
    except ValueError:
        quantity = 1
    parsed_variant = int(variant_id) if variant_id else None
    data = get_variant_price(product_id=product_id, variant_id=parsed_variant, user=request.user, quantity=quantity)
    
    from cart.models import CartItem
    from cart.selectors import get_cart_for_request
    
    cart = get_cart_for_request(request=request)
    if parsed_variant:
        cart_item = (
            CartItem.objects.filter(
                cart=cart, product_id=product_id, variant_id=parsed_variant, combo__isnull=True
            ).first()
            if cart
            else None
        )
    else:
        cart_item = (
            CartItem.objects.filter(
                cart=cart, product_id=product_id, variant__isnull=True, combo__isnull=True
            ).first()
            if cart
            else None
        )
    data["is_in_cart"] = cart_item is not None

    return JsonResponse(data)


@require_GET
def delivery_estimate_view(request: HttpRequest, product_id: int) -> JsonResponse:
    """JSON endpoint for delivery estimate widget on PDP."""
    from catalog.selectors import get_products_by_ids

    products = get_products_by_ids(product_ids=[product_id])
    if not products:
        raise Http404("Product not found")
    product = products[0]
    city_slug = request.GET.get("city", "ernakulam")
    city = get_city_by_slug(slug=city_slug)
    if city is None:
        active_cities = get_active_cities()
        city = active_cities[0] if active_cities else None
    if city is None:
        raise Http404("City not found")
    estimate = get_earliest_delivery_estimate(product=product, destination_city=city)
    return JsonResponse(estimate)


@require_GET
@never_cache
def rental_list_view(request: HttpRequest) -> HttpResponse:
    """
    Rentals listing page.

    @never_cache prevents a stale "Add to Cart"/"View Cart" state on the
    product cards after a browser-back navigation. See pdp_view for the
    full rationale.
    """
    from catalog.selectors import _primary_image_prefetch, _variant_list_prefetch, PLP_CARD_FIELDS
    products = (
        Product.objects.filter(is_active=True, is_rental=True, show_rental_storefront=True)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variant_list_prefetch())
        .only(*PLP_CARD_FIELDS)
    )
    return render(request, "catalog/rentals.html", {"products": list(products)})


@require_GET
@never_cache
def combo_list_view(request: HttpRequest) -> HttpResponse:
    """Storefront listing of active product combos."""
    combos = get_active_combos()
    return render(request, "catalog/combo_list.html", {"combos": combos})


@require_GET
@never_cache
def combo_detail_view(request: HttpRequest, slug: str) -> HttpResponse:
    """Combo detail page — bundled products, combined price, add-to-cart."""
    combo = get_combo_by_slug(slug=slug)
    if combo is None:
        raise Http404("Combo not found")

    from cart.models import CartItem
    from cart.selectors import get_cart_for_request

    cart = get_cart_for_request(request=request)
    combo_items = list(combo.items.all())

    reserved_by_key: dict[tuple[int, int | None], int] = {}
    if cart and combo_items:
        reserved_rows = (
            CartItem.objects.filter(cart=cart)
            .values("product_id", "variant_id")
            .annotate(total=Sum("quantity"))
        )
        reserved_by_key = {(row["product_id"], row["variant_id"]): row["total"] for row in reserved_rows}

    max_combo_qty = 0
    limiting_component_name = ""
    if combo.is_available:
        for item in combo_items:
            raw_stock = item.variant.stock_quantity if item.variant_id else item.product.stock_quantity
            reserved = reserved_by_key.get((item.product_id, item.variant_id), 0)
            available = max(raw_stock - reserved, 0)
            item_max = available // item.quantity
            if limiting_component_name == "" or item_max < max_combo_qty:
                max_combo_qty = item_max
                limiting_component_name = (
                    f"{item.product.name} \u2014 {item.variant.name}" if item.variant_id else item.product.name
                )

    combo_in_cart = bool(cart) and CartItem.objects.filter(cart=cart, combo=combo).exists()

    return render(
        request,
        "catalog/combo_detail.html",
        {
            "combo": combo,
            "max_combo_qty": max_combo_qty,
            "limiting_component_name": limiting_component_name,
            "combo_in_cart": combo_in_cart,
        },
    )


@require_POST
def submit_review_view(request, product_id: int):
    """
    Handle product review submission — either from an authenticated customer's
    order-history page, or an unauthenticated visitor following a signed
    review-invite link emailed on delivery (see catalog.services.create_review_invite_token).
    Both paths require proof of a delivered order containing this product.
    """
    from django.urls import reverse
    from orders.models import Order, OrderItem, OrderStatus

    product = get_object_or_404(Product, pk=product_id, is_active=True)
    redirect_url = f"{reverse('catalog:pdp', args=[product.slug])}#reviews"
    form = ReviewSubmissionForm(request.POST)

    token = request.POST.get("token", "")
    order = None
    customer = None

    if token:
        try:
            payload = verify_review_invite_token(token=token)
        except signing.BadSignature:
            messages.error(request, "This review link is invalid or has expired.")
            return redirect(redirect_url)
        if payload.get("product_id") != product.pk:
            messages.error(request, "This review link doesn't match this product.")
            return redirect(redirect_url)
        order = (
            Order.objects.filter(pk=payload.get("order_id"), order_status=OrderStatus.DELIVERED)
            .select_related("customer_profile")
            .first()
        )
        customer = order.customer_profile if order else None
    elif request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        customer = request.user.customer_profile
        order_id = request.POST.get("order_id", "")
        if order_id.isdigit():
            order = Order.objects.filter(
                pk=order_id,
                customer_profile=customer,
                order_status=OrderStatus.DELIVERED,
            ).first()

    if order is None or customer is None:
        messages.error(
            request,
            "We couldn't verify a delivered order for this review. Please use the link from "
            "your delivery email, or sign in.",
        )
        return redirect(redirect_url)

    if not OrderItem.objects.filter(order=order, product=product).exists():
        messages.error(request, "This product wasn't part of that order.")
        return redirect(redirect_url)

    if Review.objects.filter(order=order, product=product).exists():
        messages.info(request, "You've already reviewed this product for this order.")
        return redirect(redirect_url)

    if form.is_valid():
        try:
            submit_review(
                product=product,
                customer=customer,
                order=order,
                rating=form.cleaned_data["rating"],
                title=form.cleaned_data["title"],
                body=form.cleaned_data["body"],
                is_verified_purchase=True,
            )
        except IntegrityError:
            # Lost a race with a duplicate submission for this order+product.
            messages.info(request, "You've already reviewed this product for this order.")
        else:
            messages.success(request, "Thank you for your valuable review!")
    else:
        messages.error(request, "There was an error with your review submission. Please check your inputs.")

    return redirect(redirect_url)
