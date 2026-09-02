"""ModelForms used by the admin dashboard CRUD screens."""

from __future__ import annotations

from django import forms
from django.utils import timezone
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
from core.models import SiteSettings
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

    def _check_variant_sku_uniqueness(self, active_variants):

        from catalog.models import ProductVariant

        by_suffix: dict[str, list] = {}
        for vform in active_variants:
            suffix = vform.cleaned_data.get("sku_suffix")
            if not suffix:
                continue
            by_suffix.setdefault(suffix, []).append(vform)

        if not by_suffix:
            return

        for suffix, vforms in by_suffix.items():
            if len(vforms) > 1:
                for vform in vforms:
                    vform.add_error(
                        "sku_suffix",
                        "This SKU is already used by another variant below.",
                    )

        existing = ProductVariant.objects.filter(sku_suffix__in=by_suffix.keys())
        exclude_pks = [
            vform.instance.pk
            for vforms in by_suffix.values()
            for vform in vforms
            if vform.instance.pk
        ]
        if exclude_pks:
            existing = existing.exclude(pk__in=exclude_pks)
        taken = set(existing.values_list("sku_suffix", flat=True))
        for suffix in taken:
            for vform in by_suffix[suffix]:
                vform.add_error(
                    "sku_suffix",
                    "A product variant with this SKU already exists.",
                )

    def clean(self):
        cleaned = super().clean()
        active_variants = self._active_variant_forms()

        if active_variants is None and self._variants_formset is not None:
            
            return cleaned

        has_variants = bool(active_variants) if active_variants is not None else (
            bool(self.instance.pk) and self.instance.variants.exists()
        )

        if has_variants:

            self._check_variant_sku_uniqueness(active_variants)

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

class ProductLevelImageFormSet(forms.BaseInlineFormSet):

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(variant__isnull=True)


ProductImageFormSet = forms.inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    formset=ProductLevelImageFormSet,
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only stop the user picking a past date when the coupon is being
        # created — an existing coupon may legitimately have a valid_from
        # in the past (it already started) and editing it shouldn't be
        # blocked just because that field is untouched.
        now = timezone.localtime(timezone.now())
        for field_name in ("valid_from", "valid_until"):
            floor = now
            current = getattr(self.instance, field_name, None)
            if current is not None:
                current = timezone.localtime(current)
                if current < floor:
                    floor = current
            self.fields[field_name].widget.attrs["min"] = floor.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()

        now = timezone.now()
        for field_name, label in (("valid_from", "Valid From"), ("valid_until", "Valid To")):
            value = cleaned.get(field_name)
            if value is None:
                continue
            original = getattr(self.instance, field_name, None) if self.instance.pk else None
            if original is not None and original < now:

                if value < original:
                    self.add_error(field_name, f"{label} date can't be set earlier than its current value.")
            elif value < now:
                self.add_error(field_name, f"{label} date cannot be in the past.")

        valid_from = cleaned.get("valid_from")
        valid_until = cleaned.get("valid_until")
        if valid_from and valid_until and valid_until < valid_from:
            self.add_error("valid_until", "Valid To date cannot be earlier than Valid From date.")

        return cleaned



class FlashSaleForm(forms.ModelForm):
    class Meta:
        model = FlashSale
        fields = ["name", "products", "discount_percentage", "starts_at", "ends_at", "is_active"]
        widgets = {"starts_at": _DATETIME, "ends_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same reasoning as CouponForm: only enforce "no past dates" on
        # creation so an in-progress flash sale can still be edited.
        now = timezone.localtime(timezone.now())
        for field_name in ("starts_at", "ends_at"):
            floor = now
            current = getattr(self.instance, field_name, None)
            if current is not None:
                current = timezone.localtime(current)
                if current < floor:
                    floor = current
            self.fields[field_name].widget.attrs["min"] = floor.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()

        now = timezone.now()
        for field_name, label in (("starts_at", "Start"), ("ends_at", "End")):
            value = cleaned.get(field_name)
            if value is None:
                continue
            original = getattr(self.instance, field_name, None) if self.instance.pk else None
            if original is not None and original < now:
                if value < original:
                    self.add_error(field_name, f"{label} date can't be set earlier than its current value.")
            elif value < now:
                self.add_error(field_name, f"{label} date cannot be in the past.")

        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        if starts_at and ends_at and ends_at < starts_at:
            self.add_error("ends_at", "End date cannot be earlier than start date.")

        return cleaned


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
        for field_name, field in self.fields.items():
            if field_name != "logo":
                if "class" in field.widget.attrs:
                    field.widget.attrs["class"] += " form-control"
                else:
                    field.widget.attrs["class"] = "form-control"


class ContactInquiryReplyForm(forms.Form):
    """Compose-and-send reply to a storefront contact inquiry, sent by the
    server over SMTP rather than handed off to the user's OS mail client."""

    subject = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 8}),
    )


class OrderStatusForm(forms.Form):
    """Free-standing form for applying an order status transition."""

    new_status = forms.ChoiceField(choices=[])
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, allowed_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_status"].choices = allowed_choices or []
