"""HTTP views for the cms app; thin request parsing delegating to selectors/services."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from catalog.selectors import get_homepage_product_rails
from cms.selectors import get_active_homepage_sections
from cms.services import get_section_render_context
from core.seo import seo_context


@require_GET
@never_cache
def homepage_view(request: HttpRequest) -> HttpResponse:
    """
    Render the CMS-driven homepage with zero DB reads for section config.

    @never_cache sends Cache-Control: no-store — without it, browsers may
    serve this page from disk cache or restore it from the back/forward
    cache on a browser-back navigation, showing a stale "Add to Cart"
    button on a product card whose cart state actually changed on another
    page (e.g. the PDP) in between. See catalog.views.pdp_view for the
    same fix applied to the product detail page.
    """
    sections = get_active_homepage_sections()
    product_rails = get_homepage_product_rails()
    section_contexts = [
        {
            "section_type": section["section_type"],
            "partial": f"cms/sections/{section['section_type']}.html",
            "context": get_section_render_context(section=section, product_rails=product_rails),
        }
        for section in sections
    ]
    context = seo_context(
        request=request,
        title="Hair Care, Skin Care & Body Care | ZAYE LENNOX",
        description="Browse hair care, skin care, and body care products available in Kerala.",
    )
    context["section_contexts"] = section_contexts
    return render(request, "cms/homepage.html", context)
