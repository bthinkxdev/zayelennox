"""Catalog management views: products, categories, occasions, brands, recipients, reviews."""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Case, Count, F, IntegerField, Min, Max, Q, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from catalog.models import Brand, Category, Product, Review
from core.models import Currency
from dashboard import forms
from dashboard.access import dashboard_required
from dashboard.views.base import (
    DashboardCreateView,
    DashboardDeleteView,
    DashboardListView,
    DashboardUpdateView,
)
from reports.models import DailyProductPerformance


class ProductListView(DashboardListView):
    model = Product
    template_name = "dashboard/catalog/product_list.html"
    nav_section = "products"
    url_basename = "product"
    singular_name = "Product"
    plural_name = "Products"
    search_fields = ["name", "sku"]
    select_related = ["category", "brand"]
    prefetch_related = ["images"]
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()

        # Product.stock_quantity isn't maintained once a product has
        # variants (sales route through ProductVariant.stock_quantity - see
        # Product.is_in_stock), so both the status filter below and the
        # "Stock" column in the table need a variant-aware number instead
        # of reading the stale product-level field directly. We annotate
        # every row with the "worst-stocked variant" as effective_stock
        # (matching "low" = any variant at/below threshold) and count how
        # many variants are still in stock, so the template can tell "0 of
        # 3 variants in stock" (fully out) apart from "1 of 3 low".
        qs = qs.annotate(
            variant_count=Count("variants", distinct=True),
            min_variant_stock=Min("variants__stock_quantity"),
            max_variant_stock=Max("variants__stock_quantity"),
            effective_stock=Case(
                When(variant_count=0, then=F("stock_quantity")),
                default=F("min_variant_stock"),
                output_field=IntegerField(),
            ),
        )

        status = self.request.GET.get("status", "")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        elif status == "low":
            # "Low" = the worst-stocked variant (or the product itself, if
            # it has no variants) is at or below the threshold.
            qs = qs.filter(effective_stock__lte=F("low_stock_threshold"))
        elif status == "out":
            # "Out" = every variant is at zero (mirrors Product.is_in_stock).
            qs = qs.filter(
                Q(variant_count=0, stock_quantity=0)
                | Q(variant_count__gt=0, max_variant_stock=0)
            )
        category = self.request.GET.get("category", "")
        if category.isdigit():
            qs = qs.filter(category_id=int(category))

        if self.request.GET.get("sort") == "top_selling":
            self.top_selling_date = (
                DailyProductPerformance.objects.order_by("-report_date")
                .values_list("report_date", flat=True)
                .first()
            )
            if self.top_selling_date:
                qs = qs.filter(
                    daily_performance_reports__report_date=self.top_selling_date
                ).annotate(
                    top_selling_revenue=F("daily_performance_reports__revenue"),
                ).order_by("-top_selling_revenue")
            else:
                qs = qs.none()
        else:
            self.top_selling_date = None

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        default_currency = Currency.objects.filter(is_default=True).first()
        context["currency_symbol"] = default_currency.symbol if default_currency else ""
        context["categories"] = Category.objects.order_by("name")
        context["status_filter"] = self.request.GET.get("status", "")
        context["category_filter"] = self.request.GET.get("category", "")
        context["sort_filter"] = self.request.GET.get("sort", "")
        context["top_selling_date"] = getattr(self, "top_selling_date", None)
        return context


class ProductDeleteView(DashboardDeleteView):
    model = Product
    nav_section = "products"
    url_basename = "product"
    singular_name = "Product"


def _render_product_form(request, product, mode):
    if request.method == "POST":

        variants = forms.ProductVariantFormSet(request.POST, instance=product, prefix="variants")
        form = forms.ProductForm(
            request.POST, request.FILES, instance=product, variants_formset=variants
        )
        images = forms.ProductImageFormSet(
            request.POST, request.FILES, instance=product, prefix="images"
        )
        specifications = forms.ProductSpecificationFormSet(
            request.POST, instance=product, prefix="specifications"
        )
        documents = forms.ProductDocumentFormSet(
            request.POST, request.FILES, instance=product, prefix="documents"
        )
        if (
            form.is_valid()
            and variants.is_valid()
            and images.is_valid()
            and specifications.is_valid()
            and documents.is_valid()
        ):
            product = form.save()
            _save_variants(product, variants, request)
            images.instance = product
            images.save()
            _normalize_primary_image(product)
            specifications.instance = product
            specifications.save()
            documents.instance = product
            documents.save()
            if not product.variants.exists() and product.stock_quantity == 0:
                # The base stock field is read-only (and easy to forget
                # about) while a product has variants - if the vendor just
                # removed the last variant and saved without updating it,
                # make sure that's a deliberate choice and not a leftover
                # stale 0 from when variants were tracking stock instead.
                messages.warning(
                    request,
                    "This product has no variants and its stock quantity is 0, "
                    "so it can't be sold. Update the Inventory stock quantity "
                    "if that isn't intentional.",
                )
            messages.success(request, f"Product {'created' if mode == 'create' else 'updated'}.")
            return redirect("dashboard:product-list")
    else:
        variants = forms.ProductVariantFormSet(instance=product, prefix="variants")
        if product is None:

            variants.extra = 0
        form = forms.ProductForm(instance=product, variants_formset=variants)
        images = forms.ProductImageFormSet(instance=product, prefix="images")
        specifications = forms.ProductSpecificationFormSet(
            instance=product, prefix="specifications"
        )
        documents = forms.ProductDocumentFormSet(instance=product, prefix="documents")


    variant_empty_form = variants.empty_form
    image_empty_form = images.empty_form
    specification_empty_form = specifications.empty_form
    document_empty_form = documents.empty_form

    for f in [
        form,
        *variants.forms,
        variant_empty_form,
        *images.forms,
        image_empty_form,
        *specifications.forms,
        specification_empty_form,
        *documents.forms,
        document_empty_form,
    ]:
        _style(f)

    context = {
        "nav_section": "products",
        "page_title": f"{'Add' if mode == 'create' else 'Edit'} Product",
        "form": form,
        "variants": variants,
        "images": images,
        "specifications": specifications,
        "documents": documents,
        "form_mode": mode,
        "product": product,
        "cancel_url": reverse("dashboard:product-list"),
        "variant_empty_form": variant_empty_form,
        "image_empty_form": image_empty_form,
        "specification_empty_form": specification_empty_form,
        "document_empty_form": document_empty_form,
    }
    
    from catalog.models import ProductVariant
    context["existing_variant_types"] = ProductVariant.objects.exclude(variant_type="").values_list("variant_type", flat=True).distinct()
    
    return render(request, "dashboard/catalog/product_form.html", context)


def _save_variants(product, variants, request):
    """
    Persist the variants formset, converting each kept variant's vendor-entered
    "price" into ProductVariant.price_delta against the product's just-saved
    base_price.

    """
    variants.instance = product
    active_forms = forms.get_active_variant_forms(variants)

    for vform in variants.forms:
        if variants.can_delete and vform.cleaned_data.get("DELETE"):
            if vform.instance.pk:
                vform.instance.delete()
            continue
        if vform not in active_forms:
            continue  # blank, unused extra row
        instance = vform.save(commit=False)
        instance.product = product
        price = vform.cleaned_data.get("price")
        if price is not None:
            instance.price_delta = price - product.base_price
        instance.save()

        _save_variant_images(product=product, variant=instance, prefix=vform.prefix, request=request)


def _save_variant_images(*, product, variant, prefix, request):
    """
    Apply one variant row's image changes.

    """
    from catalog.models import ProductImage

    delete_ids = request.POST.getlist(f"{prefix}-delete_image_ids")
    if delete_ids:

        ProductImage.objects.filter(variant=variant, pk__in=delete_ids).delete()

    new_files = request.FILES.getlist(f"{prefix}-new_images")
    created = []
    if new_files:
        next_order = ProductImage.objects.filter(variant=variant).count()
        for offset, uploaded_file in enumerate(new_files):
            created.append(
                ProductImage.objects.create(
                    product=product,
                    variant=variant,
                    image=uploaded_file,
                    display_order=next_order + offset,
                )
            )

    primary_choice = request.POST.get(f"{prefix}-primary_choice", "")
    if primary_choice.startswith("existing:"):
        chosen_pk = primary_choice.split(":", 1)[1]
        if ProductImage.objects.filter(variant=variant, pk=chosen_pk).exists():
            ProductImage.objects.filter(variant=variant).update(is_primary=False)
            ProductImage.objects.filter(variant=variant, pk=chosen_pk).update(is_primary=True)
    elif primary_choice.startswith("new:"):
        try:
            chosen_index = int(primary_choice.split(":", 1)[1])
        except ValueError:
            chosen_index = None
        if chosen_index is not None and 0 <= chosen_index < len(created):
            ProductImage.objects.filter(variant=variant).update(is_primary=False)
            created[chosen_index].is_primary = True
            created[chosen_index].save(update_fields=["is_primary"])


    _normalize_variant_primary_image(variant)


def _normalize_variant_primary_image(variant):
    images_qs = list(variant.images.order_by("display_order", "pk"))
    if not images_qs:
        return

    primary_images = [img for img in images_qs if img.is_primary]

    if not primary_images:
        images_qs[0].is_primary = True
        images_qs[0].save(update_fields=["is_primary"])
    elif len(primary_images) > 1:
        for img in primary_images[1:]:
            img.is_primary = False
            img.save(update_fields=["is_primary"])


def _normalize_primary_image(product):
    """
    Enforce exactly one primary product image after saving the images
    formset (server-side backstop behind the "Primary" checkbox's
    radio-like JS behavior on the product form, in case a request bypasses
    that JS - e.g. JS disabled, or a direct POST).

    - No image checked "Primary" -> default to the first image (by display
      order, falling back to creation order for ties), matching what the
      vendor sees as the first row.
    - More than one image checked "Primary" -> keep only the first one
      (same ordering) and uncheck the rest.
    - Exactly one checked -> leave as-is.
    """

    images_qs = list(
        product.images.filter(variant__isnull=True).order_by("display_order", "pk")
    )
    if not images_qs:
        return

    primary_images = [img for img in images_qs if img.is_primary]

    if not primary_images:
        images_qs[0].is_primary = True
        images_qs[0].save(update_fields=["is_primary"])
    elif len(primary_images) > 1:
        for img in primary_images[1:]:
            img.is_primary = False
            img.save(update_fields=["is_primary"])


def _style(form):
    """Apply Bootstrap classes to a form's widgets (shared with generic mixin)."""
    for field in form.fields.values():
        widget = field.widget
        css = widget.attrs.get("class", "")
        name = widget.__class__.__name__.lower()
        if "checkbox" in name:
            widget.attrs["class"] = (css + " form-check-input").strip()
        elif "select" in name:
            widget.attrs["class"] = (css + " form-select").strip()
        elif "file" in name:
            widget.attrs["class"] = (css + " form-control").strip()
        else:
            widget.attrs["class"] = (css + " form-control").strip()


@dashboard_required
@require_http_methods(["GET", "POST"])
def product_create(request):
    return _render_product_form(request, None, "create")


@dashboard_required
@require_http_methods(["GET", "POST"])
def product_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return _render_product_form(request, product, "edit")


class CategoryListView(DashboardListView):
    model = Category
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"
    plural_name = "Categories"
    search_fields = ["name", "slug"]
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Slug", "name": "slug"},
        {"label": "Parent", "name": "parent.name"},
        {"label": "Order", "name": "display_order"},
        {"label": "Active", "name": "is_active", "type": "bool"},
    ]


class CategoryCreateView(DashboardCreateView):
    model = Category
    form_class = forms.CategoryForm
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"


class CategoryUpdateView(DashboardUpdateView):
    model = Category
    form_class = forms.CategoryForm
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"


class CategoryDeleteView(DashboardDeleteView):
    model = Category
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"



class BrandListView(DashboardListView):
    model = Brand
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"
    plural_name = "Brands"
    search_fields = ["name", "slug"]
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Slug", "name": "slug"},
        {"label": "Featured", "name": "is_featured", "type": "bool"},
    ]


class BrandCreateView(DashboardCreateView):
    model = Brand
    form_class = forms.BrandForm
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"


class BrandUpdateView(DashboardUpdateView):
    model = Brand
    form_class = forms.BrandForm
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"


class BrandDeleteView(DashboardDeleteView):
    model = Brand
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"



class ReviewListView(DashboardListView):
    model = Review
    nav_section = "reviews"
    url_basename = "review"
    singular_name = "Review"
    plural_name = "Reviews"
    select_related = ["product", "customer__user"]
    can_create = False
    columns = [
        {"label": "Product", "name": "product.name"},
        {"label": "Rating", "name": "rating"},
        {"label": "Title", "name": "title"},
        {"label": "Status", "name": "get_moderation_status_display", "type": "badge"},
        {"label": "Submitted", "name": "created_at", "type": "datetime"},
    ]


class ReviewUpdateView(DashboardUpdateView):
    model = Review
    form_class = forms.ReviewForm
    nav_section = "reviews"
    url_basename = "review"
    singular_name = "Review"

    def form_valid(self, form):
        form.instance.moderated_by = self.request.user
        
        #clear notification 
        original_review = self.get_object()
        from notifications.models import Notification
        body_text = f'Review "{original_review.title}" on {original_review.product.name} awaits approval.'
        Notification.objects.filter(
            title="Review pending moderation", 
            body=body_text,
            is_read=False
        ).update(is_read=True)
        
        return super().form_valid(form)


class ReviewDeleteView(DashboardDeleteView):
    model = Review
    nav_section = "reviews"
    url_basename = "review"
    singular_name = "Review"

    def form_valid(self, form):
        #clear notification 
        original_review = self.get_object()
        from notifications.models import Notification
        body_text = f'Review "{original_review.title}" on {original_review.product.name} awaits approval.'
        Notification.objects.filter(
            title="Review pending moderation", 
            body=body_text,
            is_read=False
        ).update(is_read=True)
        
        return super().form_valid(form)
