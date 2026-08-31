"""Django admin registrations for the catalog app."""

from __future__ import annotations

from django.contrib import admin

from catalog.models import (
    Brand,
    Category,
    Product,
    ProductImage,
    ProductRelation,
    ProductVariant,
    ProductVideo,
    Review,
    ReviewPhoto,
    ProductSpecification,
    ProductDocument,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin for category tree."""

    list_display = ("name", "slug", "parent", "display_order", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    list_select_related = ("parent",)
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("display_order", "name")



@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    """Admin for product brands."""

    list_display = ("name", "slug", "is_featured", "updated_at")
    list_filter = ("is_featured",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    fk_name = "product"
    fields = ("image", "variant", "alt_text", "display_order", "is_primary")
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = (
        "variant_type",
        "name",
        "price_delta",
        "mrp",
        "purchase_price",
        "sku_suffix",
        "stock_quantity",
        "weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
    )


class ProductSpecificationInline(admin.TabularInline):
    model = ProductSpecification
    extra = 1


class ProductDocumentInline(admin.TabularInline):
    model = ProductDocument
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin for products — list_select_related prevents N+1 on list view."""

    list_display = (
        "name",
        "sku",
        "category",
        "brand",
        "base_price",
        "is_active",
        "is_bestseller",
        "stock_quantity",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "is_bestseller",
        "is_new_arrival",
        "is_featured",
        "category",
        "brand",
    )
    search_fields = ("name", "slug", "sku")
    list_select_related = ("category", "brand")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "slug",
                    "sku",
                    "category",
                    "brand",
                    "base_price",
                    "mrp",
                    "purchase_price",
                    "is_rental",
                    "rental_price",
                    "show_rental_storefront",
                    "color",
                    "is_active",
                    "is_featured",
                    "is_bestseller",
                    "is_new_arrival",
                    "stock_quantity",
                    "low_stock_threshold",
                    "meta_title",
                    "meta_description",
                    "og_image",
                ),
            },
        ),
        (
            "Shipping — package dimensions",
            {
                "fields": ("weight_kg", "length_cm", "width_cm", "height_cm"),
                "description": (
                    "Default packed weight/size used to book couriers (e.g. Shiprocket) for "
                    "this product. If a specific variant below needs different dimensions or "
                    "weight (e.g. a larger size), set an override on that variant — otherwise "
                    "leave variant overrides blank and these product-level defaults apply."
                ),
            },
        ),
    )
    inlines = [
        ProductVariantInline,
        ProductImageInline,
        ProductSpecificationInline,
        ProductDocumentInline,
    ]
    ordering = ("name",)


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Admin for product variants."""

    list_display = (
        "product",
        "variant_type",
        "name",
        "price_delta",
        "stock_quantity",
        "has_shipping_override",
    )
    list_filter = ("variant_type",)
    search_fields = ("product__name", "product__sku", "name")
    list_select_related = ("product",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "product",
                    "variant_type",
                    "name",
                    "price_delta",
                    "mrp",
                    "purchase_price",
                    "sku_suffix",
                    "stock_quantity",
                )
            },
        ),
        (
            "Shipping override (optional)",
            {
                "fields": ("weight_kg", "length_cm", "width_cm", "height_cm"),
                "description": (
                    "Leave all four blank to inherit the product's default package "
                    "dimensions. Only fill these in if this specific variant is packed "
                    "differently (e.g. a larger size)."
                ),
            },
        ),
    )

    @admin.display(description="Shipping override", boolean=True)
    def has_shipping_override(self, obj) -> bool:
        return any(
            getattr(obj, field) is not None
            for field in ("weight_kg", "length_cm", "width_cm", "height_cm")
        )


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    """Admin for product images."""

    list_display = ("product", "variant", "display_order", "is_primary", "updated_at")
    list_filter = ("is_primary",)
    search_fields = ("product__name", "alt_text", "variant__name")
    list_select_related = ("product", "variant")


@admin.register(ProductVideo)
class ProductVideoAdmin(admin.ModelAdmin):
    """Admin for product videos."""

    list_display = ("product", "video_url", "updated_at")
    search_fields = ("product__name",)
    list_select_related = ("product",)


@admin.register(ProductRelation)
class ProductRelationAdmin(admin.ModelAdmin):
    """Admin for product relationships."""

    list_display = ("product", "related_product", "relation_type", "updated_at")
    list_filter = ("relation_type",)
    search_fields = ("product__name", "related_product__name")
    list_select_related = ("product", "related_product")


class ReviewPhotoInline(admin.TabularInline):
    model = ReviewPhoto
    extra = 0


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Admin for customer reviews."""

    list_display = (
        "product",
        "customer",
        "rating",
        "moderation_status",
        "is_verified_purchase",
        "updated_at",
    )
    list_filter = ("moderation_status", "rating", "is_verified_purchase")
    search_fields = ("product__name", "customer__user__email", "title")
    list_select_related = ("product", "customer", "customer__user", "moderated_by")
    inlines = [ReviewPhotoInline]


@admin.register(ReviewPhoto)
class ReviewPhotoAdmin(admin.ModelAdmin):
    """Admin for review photos."""

    list_display = ("review", "updated_at")
    list_select_related = ("review", "review__product")
