"""SEO helpers — meta tags, canonical URLs, hreflang, and JSON-LD."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse, translate_url
from django.utils.translation import get_language


def resolve_meta_title(*, obj: Any, fallback: str) -> str:
    """Return meta_title from an SEOModel-capable object or fallback."""
    title = (getattr(obj, "meta_title", None) or "").strip()
    return (title or fallback)[:70]


def resolve_meta_description(*, obj: Any, fallback: str) -> str:
    """Return meta_description from an SEOModel-capable object or fallback."""
    description = (getattr(obj, "meta_description", None) or "").strip()
    return (description or fallback)[:160]


def resolve_og_image_url(*, obj: Any, request: HttpRequest) -> str:
    """Return absolute OG image URL from object or empty string."""
    og_image = getattr(obj, "og_image", None)
    if og_image and getattr(og_image, "url", None):
        return request.build_absolute_uri(og_image.url)
    return ""


def build_hreflang_urls(*, request: HttpRequest) -> list[dict[str, str]]:
    """
    Build EN/AR alternate URLs for the current path.

    Uses Django's translate_url to swap locale prefix without duplicating routes.
    """
    alternates: list[dict[str, str]] = []
    current_path = request.get_full_path()
    for lang_code, _label in settings.LANGUAGES:
        localized = translate_url(current_path, lang_code)
        alternates.append(
            {
                "lang_code": lang_code,
                "url": request.build_absolute_uri(localized),
            }
        )
    alternates.append(
        {
            "lang_code": "x-default",
            "url": request.build_absolute_uri(translate_url(current_path, settings.LANGUAGE_CODE)),
        }
    )
    return alternates


def build_plp_canonical_url(
    *,
    request: HttpRequest,
    category_slug: str | None = None,
) -> str:
    """
    Canonical URL for PLP — filtered query params canonicalize to category or shop root.

    Prevents duplicate-content penalties from sort/filter query strings.
    """
    from django.urls import reverse

    if category_slug:
        path = reverse("catalog:plp-category", kwargs={"category_slug": category_slug})
    else:
        path = reverse("catalog:plp")
    return request.build_absolute_uri(path)


def build_product_json_ld(
    *,
    product: Any,
    price: Decimal | str,
    request: HttpRequest,
    average_rating: Optional[float] = None,
    review_count: int = 0,
) -> dict[str, Any]:
    """
    Build schema.org Product JSON-LD for Google Rich Results.

    Includes Offer (price/availability) and AggregateRating when reviews exist.
    """
    from django.urls import reverse
    from core.selectors import get_default_currency

    currency = get_default_currency()
    currency_code = currency.code if currency else ""

    availability = (
        "https://schema.org/InStock" if product.is_in_stock else "https://schema.org/OutOfStock"
    )
    image_url = ""
    images = getattr(product, "image_list", None) or getattr(product, "images", None)
    if images:
        first = images[0] if isinstance(images, list) else images.first()
        if first and getattr(first, "image", None):
            image_url = request.build_absolute_uri(first.image.url)

    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name,
        "url": request.build_absolute_uri(reverse("catalog:pdp", kwargs={"slug": product.slug})),
        "offers": {
            "@type": "Offer",
            "priceCurrency": currency_code,
            "price": str(price),
            "availability": availability,
            "url": request.build_absolute_uri(
                reverse("catalog:pdp", kwargs={"slug": product.slug})
            ),
        },
    }
    if image_url:
        data["image"] = image_url

    if product.sku:
        data["sku"] = product.sku

    description = resolve_meta_description(obj=product, fallback=product.name)
    if description:
        data["description"] = description

    if review_count > 0 and average_rating is not None:
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": round(float(average_rating), 1),
            "reviewCount": review_count,
        }

    return data


def build_storefront_json_ld(*, request: HttpRequest) -> list[dict[str, Any]]:
    """Build Organization and WebSite schema for the public storefront."""
    from core.services import get_site_settings

    site_settings = get_site_settings()
    site_name = site_settings.site_name or "ZAYE LENNOX"
    home_url = request.build_absolute_uri(reverse("cms:homepage"))
    shop_url = request.build_absolute_uri(reverse("catalog:plp"))
    logo_url = ""
    if site_settings.logo and getattr(site_settings.logo, "url", None):
        logo_url = request.build_absolute_uri(site_settings.logo.url)

    organization: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": site_name,
        "url": home_url,
    }
    if logo_url:
        organization["logo"] = logo_url

    same_as = [
        url
        for url in (
            site_settings.facebook_url,
            site_settings.instagram_url,
            site_settings.twitter_url,
        )
        if url
    ]
    if same_as:
        organization["sameAs"] = same_as

    contact_points: list[dict[str, Any]] = []
    if site_settings.vendor_email:
        contact_points.append(
            {
                "@type": "ContactPoint",
                "email": site_settings.vendor_email,
                "contactType": "customer support",
                "areaServed": "IN",
                "availableLanguage": ["English"],
            }
        )
    if getattr(settings, "STORE_PHONE", ""):
        contact_points.append(
            {
                "@type": "ContactPoint",
                "telephone": settings.STORE_PHONE,
                "contactType": "customer support",
                "areaServed": "IN",
                "availableLanguage": ["English"],
            }
        )
    if contact_points:
        organization["contactPoint"] = contact_points

    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": site_name,
        "url": home_url,
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{shop_url}?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }
    return [organization, website]


def seo_context(
    *,
    request: HttpRequest,
    obj: Any | None = None,
    title: str,
    description: str,
    canonical_url: str | None = None,
    json_ld: list[dict[str, Any]] | None = None,
    include_storefront_json_ld: bool = False,
) -> dict[str, Any]:
    """Assemble standard SEO template context for any page."""
    if obj is not None:
        title = resolve_meta_title(obj=obj, fallback=title)
        description = resolve_meta_description(obj=obj, fallback=description)

    canonical = canonical_url or request.build_absolute_uri(request.path)
    structured_data = list(json_ld or [])
    if include_storefront_json_ld:
        structured_data.extend(build_storefront_json_ld(request=request))

    return {
        "seo_title": title,
        "seo_description": description,
        "seo_canonical_url": canonical,
        "seo_og_image": resolve_og_image_url(obj=obj, request=request) if obj else "",
        "seo_hreflang_urls": build_hreflang_urls(request=request),
        "seo_lang": get_language() or settings.LANGUAGE_CODE,
        "seo_robots": "index,follow",
        "seo_json_ld": [
            json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            for item in structured_data
        ],
    }
