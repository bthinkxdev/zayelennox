"""Template context processors for storefront chrome."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from cart.selectors import get_cart_count, get_wishlist_count, get_wishlist_product_ids, get_cart_product_ids
from catalog.selectors import get_category_by_slug, get_category_tree
from core.selectors import get_currency_by_code, get_default_currency
from core.services import get_site_settings
from delivery.selectors import get_active_countries


def _resolve_current_category(request: HttpRequest):
    """
    Resolve the category the customer is currently browsing, if any.

    Used by the header's search category dropdown so it reflects where the
    customer actually is instead of always saying "All Categories" —
    whether they landed on a category page directly or filtered the PLP
    via ?category=<id>.
    """
    match = getattr(request, "resolver_match", None)
    if match is None:
        return None

    if match.view_name == "catalog:plp-category":
        slug = match.kwargs.get("category_slug")
        return get_category_by_slug(slug=slug) if slug else None

    if match.view_name == "catalog:plp":
        category_id = request.GET.get("category")
        if category_id and category_id.isdigit():
            from catalog.models import Category

            return Category.objects.filter(pk=category_id, is_active=True).first()
        return None

    return None


def storefront(request: HttpRequest) -> dict[str, Any]:
    """Inject navigation, cart, and locale data into every template."""
    if request.method == "GET":
        path = request.path_info
        is_checkout_or_payment = (
            path.startswith("/checkout/")
            or path.startswith("/payments/")
            or path.startswith("/admin/")
            or path.startswith("/static/")
            or path.startswith("/media/")
            or path.startswith("/__debug__/")
            or path == "/favicon.ico"
            or path.startswith("/cart/count/")
            or path.startswith("/cart/drawer/")
            or path.startswith("/cart/wishlist/count/")
        )
        if not is_checkout_or_payment:
            pass


    default_currency = get_default_currency()
    session_currency = request.session.get("storefront_currency", "")
    display_currency = (
        get_currency_by_code(code=session_currency) if session_currency else default_currency
    )
    countries = get_active_countries()
    session_country = request.session.get("storefront_country", "")
    active_country = next(
        (c for c in countries if c.code == session_country),
        countries[0] if countries else None,
    )
    wishlist_product_ids = get_wishlist_product_ids(request=request)
    
    from cms.models import Page

    return {
        "site_settings": get_site_settings(),
        "category_tree": get_category_tree(),
        "current_search_category": _resolve_current_category(request),
        "cart_count": get_cart_count(request=request),
        "cart_product_ids": get_cart_product_ids(request=request),
        "wishlist_count": get_wishlist_count(request=request),
        "wishlist_product_ids": wishlist_product_ids,
        "default_currency": default_currency,
        "display_currency": display_currency,
        "session_language": request.session.get("django_language", ""),
        "session_currency": session_currency,
        "countries": countries,
        "session_country": session_country,
        "active_country": active_country,
        "shell_only": request.META.get("HTTP_X_SHELL_RERENDER") == "true",
        "cms_pages": Page.objects.filter(is_published=True),
    }
