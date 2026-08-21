"""ModelForms used by the admin dashboard CRUD screens."""

from __future__ import annotations

from django import forms
from django.utils.text import slugify

from accounts.models import CustomerProfile
from catalog.models import (
    Brand,
    Category,
    Product,
    ProductDocument,
    ProductImage,
    ProductSpecification,
    ProductVariant,
    Review,
)
from cms.models import (
    BlogPost,
    FAQItem,
    HeroSlide,
    HomepageSection,
    Page,
    PolicyDocument,
    SecondarySlide,
)
from core.models import SiteSettings, Currency
from delivery.models import City
from marketing.models import Coupon, FlashSale, NewsletterSubscriber

_DATE = forms.DateInput(attrs={"type": "date"})
_DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
_TIME = forms.TimeInput(attrs={"type": "time"})


class SlugAutoMixin(forms.ModelForm):
    """Auto-populate an empty ``slug`` from ``name``/``title`` on save."""

    def clean(self):
        cleaned = super().clean()
        if "slug" in self.fields and not cleaned.get("slug"):
            source = cleaned.get("name") or cleaned.get("title")
            if source:
                cleaned["slug"] = slugify(source)
        return cleaned


_DIMENSION_FIELDS = ("weight_kg", "length_cm", "width_cm", "height_cm")


def get_active_variant_forms(formset):
    """
    Forms in a product's variants formset that represent a real, kept variant —
    i.e. not a blank unused extra row, and not marked for deletion.

    """
    active = []
    for form in formset.forms:
        if not hasattr(form, "cleaned_data"):
            continue
        if formset.can_delete and form.cleaned_data.get("DELETE"):
            continue
        if not form.has_changed() and not form.instance.pk:
            continue
        active.append(form)
    return active


class ProductForm(SlugAutoMixin):
    class Meta:
        model = Product
        fields = [
            "name",
            "slug",
            "sku",
            "category",
            "brand",
            "base_price",
            "mrp",
            "purchase_price",

            "color",
            "stock_quantity",
            "low_stock_threshold",
            "is_active",
            "is_featured",
            "is_bestseller",
            "is_new_arrival",
            "weight_kg",
            "length_cm",
            "width_cm",
            "height_cm",
            "meta_title",
            "meta_description",
            "og_image",
        ]
        error_messages = {
            "name": {"required": "Product name is required."},
            "sku": {"required": "SKU is required."},
            "category": {"required": "Category is required."},
            "stock_quantity": {"required": "Stock quantity is required."},
        }

    def __init__(self, *args, variants_formset=None, **kwargs):
        super().__init__(*args, **kwargs)
       
        self._variants_formset = variants_formset
        self.fields["slug"].required = False
        
        for name in ("base_price", "mrp", "purchase_price", *_DIMENSION_FIELDS):
            self.fields[name].required = False
        
        if not self.instance.pk:
            for name in _DIMENSION_FIELDS:
                self.initial[name] = None
                self.fields[name].widget.attrs["placeholder"] = "0.00"

    def _active_variant_forms(self):
        fs = self._variants_formset
        if fs is None:
            return None
        if not fs.is_valid():
            return None
        return get_active_variant_forms(fs)

    def clean(self):
        cleaned = super().clean()
        active_variants = self._active_variant_forms()

        if active_variants is None and self._variants_formset is not None:
            
            return cleaned

        has_variants = bool(active_variants) if active_variants is not None else (
            bool(self.instance.pk) and self.instance.variants.exists()
        )

        if has_variants:
            
            prices = []
            for vform in active_variants:
                price = vform.cleaned_data.get("price")
                if price in (None, ""):
                    vform.add_error("price", "Price is required for each variant.")
                else:
                    prices.append(price)
            if prices:
                cleaned["base_price"] = min(prices)

            
            all_variants_have_dims = active_variants and all(
                all(vform.cleaned_data.get(f) not in (None, "") for f in _DIMENSION_FIELDS)
                for vform in active_variants
            )
            if not all_variants_have_dims:
                for f in _DIMENSION_FIELDS:
                    if cleaned.get(f) in (None, ""):
                        self.add_error(
                            f,
                            "Required unless every variant below supplies its own "
                            "weight/length/width/height.",
                        )
        else:
            
            for field_name, label in (
                ("base_price", "Base price"),
                ("mrp", "MRP"),
                ("purchase_price", "Purchase price"),
            ):
                if cleaned.get(field_name) in (None, ""):
                    self.add_error(field_name, f"{label} is required.")
            for f in _DIMENSION_FIELDS:
                if cleaned.get(f) in (None, ""):
                    self.add_error(f, "Required for courier booking.")

        return cleaned


class CategoryForm(SlugAutoMixin):
    class Meta:
        model = Category
        fields = [
            "name",
            "slug",
            "parent",
            "display_order",
            "is_active",
            "meta_title",
            "meta_description",
            "og_image",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False



class BrandForm(SlugAutoMixin):
    class Meta:
        model = Brand
        fields = ["name", "slug", "logo", "is_featured"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False



class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["moderation_status"]


class ProductVariantForm(forms.ModelForm):
    
    price = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label="Price",
        help_text="Actual selling price for this variant — what the customer pays.",
        widget=forms.NumberInput(attrs={"placeholder": "e.g. 499.00", "step": "0.01"}),
    )

    class Meta:
        model = ProductVariant
        fields = [
            "variant_type",
            "name",
            "sku_suffix",
            "stock_quantity",
            "mrp",
            "purchase_price",
            "weight_kg",
            "length_cm",
            "width_cm",
            "height_cm",
        ]
        widgets = {
            "variant_type": forms.TextInput(attrs={
                "list": "variant-type-list",
                "class": "form-control",
                "placeholder": "e.g. Size, Packaging, Color"
            }),
            "mrp": forms.NumberInput(attrs={"placeholder": "Optional", "step": "0.01"}),
            "purchase_price": forms.NumberInput(attrs={"placeholder": "Optional", "step": "0.01"}),
            "weight_kg": forms.NumberInput(attrs={"placeholder": "Product default", "step": "0.001"}),
            "length_cm": forms.NumberInput(attrs={"placeholder": "Product default", "step": "0.01"}),
            "width_cm": forms.NumberInput(attrs={"placeholder": "Product default", "step": "0.01"}),
            "height_cm": forms.NumberInput(attrs={"placeholder": "Product default", "step": "0.01"}),
        }
        error_messages = {
            "variant_type": {"required": "Variant type is required."},
            "name": {"required": "Name is required."},
            "sku_suffix": {"required": "SKU suffix is required."},
            "stock_quantity": {"required": "Stock quantity is required."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("weight_kg", "length_cm", "width_cm", "height_cm", "mrp", "purchase_price"):
            self.fields[name].required = False
        
        if self.instance.pk and self.instance.product_id:
            self.initial.setdefault("price", self.instance.product.base_price + self.instance.price_delta)

    def has_changed(self):
        """Ignore empty extra forms even if fields have model defaults (like stock_quantity=0)."""
        changed = super().has_changed()
        if changed:
            #if every field in the POST data is empty, it's an untouched extra form.
            for name in self.fields:
                prefixed_name = self.add_prefix(name)
                val = self.data.get(prefixed_name)
                if val:  #any non-empty string means user interacted
                    return True
            return False
        return changed

ProductVariantFormSet = forms.inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    extra=1,
    can_delete=True,
)

class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ["image", "alt_text", "display_order", "is_primary"]
        error_messages = {
            "image": {"required": "Image file is required."},
            "alt_text": {"required": "Alt text is required."},
            "display_order": {"required": "Display order is required."},
        }

ProductImageFormSet = forms.inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    extra=1,
    can_delete=True,
)
class ProductSpecificationForm(forms.ModelForm):
    class Meta:
        model = ProductSpecification
        fields = ["name", "value", "display_order"]
        error_messages = {
            "name": {"required": "Specification name is required."},
            "value": {"required": "Value is required."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["display_order"].required = False
        if not self.instance.pk:
            self.initial["display_order"] = None

    def clean_display_order(self):
        val = self.cleaned_data.get("display_order")
        return val if val is not None else 0


class ProductDocumentForm(forms.ModelForm):
    class Meta:
        model = ProductDocument
        fields = ["title", "document_file", "display_order"]
        widgets = {
            "document_file": forms.FileInput(),
        }
        error_messages = {
            "title": {"required": "Document title is required."},
            "document_file": {"required": "Document file is required."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["display_order"].required = False
        if not self.instance.pk:
            self.initial["display_order"] = None

    def clean_display_order(self):
        val = self.cleaned_data.get("display_order")
        return val if val is not None else 0



ProductSpecificationFormSet = forms.inlineformset_factory(
    Product,
    ProductSpecification,
    form=ProductSpecificationForm,
    extra=1,
    can_delete=True,
)
ProductDocumentFormSet = forms.inlineformset_factory(
    Product,
    ProductDocument,
    form=ProductDocumentForm,
    extra=1,
    can_delete=True,
)


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = [
            "phone",
            "phone_verified",
            "notify_via_email",
            "notify_via_sms",
            "notify_via_whatsapp",
        ]



class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            "code",
            "discount_type",
            "discount_value",
            "min_order_value",
            "max_uses",
            "max_uses_per_customer",
            "valid_from",
            "valid_until",
            "applicable_categories",
            "is_active",
        ]
        widgets = {"valid_from": _DATETIME, "valid_until": _DATETIME}



class FlashSaleForm(forms.ModelForm):
    class Meta:
        model = FlashSale
        fields = ["name", "products", "discount_percentage", "starts_at", "ends_at", "is_active"]
        widgets = {"starts_at": _DATETIME, "ends_at": _DATETIME}


class NewsletterSubscriberForm(forms.ModelForm):
    class Meta:
        model = NewsletterSubscriber
        fields = ["email", "is_active"]


class HomepageSectionForm(forms.ModelForm):
    class Meta:
        model = HomepageSection
        fields = ["section_type", "title", "display_order", "is_active", "config"]


class HeroSlideForm(forms.ModelForm):
    class Meta:
        model = HeroSlide
        fields = ["title", "image", "video", "poster", "display_order", "is_active"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            
            from django.core.files.images import get_image_dimensions
            width, height = get_image_dimensions(image)

            if width < 1000:
                raise forms.ValidationError(
                    f"Banner image must be at least 1000px wide for good quality. Uploaded image is {width}px wide."
                )

        return image

    def clean_poster(self):
        poster = self.cleaned_data.get("poster")
        if poster:
            # Same as clean_image: any ratio accepted, cropped to 2:1 on display.
            from django.core.files.images import get_image_dimensions
            width, height = get_image_dimensions(poster)

            if width < 1200:
                raise forms.ValidationError(
                    f"Poster image must be at least 1200px wide. Uploaded image is {width}px wide."
                )

        return poster


class SecondarySlideForm(forms.ModelForm):
    class Meta:
        model = SecondarySlide
        fields = ["title", "image", "video", "poster", "display_order", "is_active"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            # Any aspect ratio is accepted here — the homepage banner is a fixed
            # 9:3 box and crops the image to fit (object-fit: cover), so we only
            # guard against low-resolution uploads rather than rejecting on ratio.
            from django.core.files.images import get_image_dimensions
            width, height = get_image_dimensions(image)

            if width < 1200:
                raise forms.ValidationError(
                    f"Banner image must be at least 1200px wide for good quality. Uploaded image is {width}px wide."
                )

        return image

    def clean_poster(self):
        poster = self.cleaned_data.get("poster")
        if poster:
            # Same as clean_image: any ratio accepted, cropped to 9:3 on display.
            from django.core.files.images import get_image_dimensions
            width, height = get_image_dimensions(poster)

            if width < 1200:
                raise forms.ValidationError(
                    f"Poster image must be at least 1200px wide. Uploaded image is {width}px wide."
                )

        return poster


class BlogPostForm(SlugAutoMixin):
    class Meta:
        model = BlogPost
        fields = [
            "title",
            "slug",
            "excerpt",
            "body",
            "is_published",
            "publish_at",
            "meta_title",
            "meta_description",
            "og_image",
        ]
        widgets = {"publish_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class PageForm(SlugAutoMixin):
    class Meta:
        model = Page
        fields = [
            "title",
            "slug",
            "body",
            "is_published",
            "publish_at",
            "meta_title",
            "meta_description",
            "og_image",
        ]
        widgets = {"publish_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class FAQItemForm(forms.ModelForm):
    class Meta:
        model = FAQItem
        fields = ["question", "answer", "display_order", "is_published", "publish_at"]
        widgets = {"publish_at": _DATETIME}


class PolicyDocumentForm(SlugAutoMixin):
    class Meta:
        model = PolicyDocument
        fields = [
            "title",
            "slug",
            "policy_type",
            "body",
            "is_published",
            "publish_at",
            "meta_title",
            "meta_description",
            "og_image",
        ]
        widgets = {"publish_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class CityForm(SlugAutoMixin):
    class Meta:
        model = City
        fields = [
            "country",
            "name",
            "slug",
            "delivery_charge_base",
            "same_day_cutoff_hour",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False





class SiteSettingsForm(forms.ModelForm):
    default_currency = forms.ModelChoiceField(
        queryset=Currency.objects.all(),
        required=False,
        empty_label="--- Select Default Currency ---",
        help_text="Select the store's default currency."
    )

    field_order = [
        "site_name",
        "logo",
        "primary_color",
        "secondary_color",
        "font_family",
        "facebook_url",
        "instagram_url",
        "twitter_url",
        "whatsapp_number",
        "vendor_email",
        "tax_rate_percent",
        "default_shipping_charge",
        "default_currency",
        "razorpay_key_id",
        "razorpay_key_secret",
    ]

    class Meta:
        model = SiteSettings
        fields = [
            "site_name",
            "logo",
            "primary_color",
            "secondary_color",
            "font_family",
            "facebook_url",
            "instagram_url",
            "twitter_url",
            "whatsapp_number",
            "vendor_email",
            "tax_rate_percent",
            "default_shipping_charge",
            "razorpay_key_id",
            "razorpay_key_secret",
        ]
        labels = {
            "vendor_email": "Email",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        default_curr = Currency.objects.filter(is_default=True).first()
        if default_curr:
            self.fields["default_currency"].initial = default_curr.pk
        for field_name, field in self.fields.items():
            if field_name != "logo":
                if "class" in field.widget.attrs:
                    field.widget.attrs["class"] += " form-control"
                else:
                    field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        instance = super().save(commit)
        new_default = self.cleaned_data.get("default_currency")
        if new_default:
            Currency.objects.update(is_default=False)
            new_default.is_default = True
            new_default.save()
            from core.selectors import invalidate_default_currency_cache
            invalidate_default_currency_cache()
        return instance


class OrderStatusForm(forms.Form):
    """Free-standing form for applying an order status transition."""

    new_status = forms.ChoiceField(choices=[])
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, allowed_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_status"].choices = allowed_choices or []
