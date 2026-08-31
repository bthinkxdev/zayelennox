"""Customer and inquiry management."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import CustomerProfile
from core.models import ContactInquiry
from dashboard import forms
from dashboard.access import dashboard_required
from dashboard.views.base import DashboardListView, DashboardUpdateView, DashboardDeleteView


class CustomerListView(DashboardListView):
    model = CustomerProfile
    nav_section = "customers"
    url_basename = "customer"
    singular_name = "Customer"
    plural_name = "Customers"
    search_fields = ["user__first_name", "user__last_name", "user__email", "user__username", "phone"]
    search_placeholder = "Search by name, email, or phone..."
    select_related = ["user"]
    can_create = False
    can_delete = False
    columns = [
        {"label": "Name", "name": "user.get_full_name"},
        {"label": "Email", "name": "user.email"},
        {"label": "Phone", "name": "get_phone"},
        {"label": "Verified", "name": "phone_verified", "type": "bool"},
    ]


class CustomerUpdateView(DashboardUpdateView):
    model = CustomerProfile
    form_class = forms.CustomerProfileForm
    nav_section = "customers"
    url_basename = "customer"
    singular_name = "Customer"


@dashboard_required
def customer_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Customer profile with addresses and recent orders."""
    profile = get_object_or_404(CustomerProfile.objects.select_related("user"), pk=pk)
    context = {
        "nav_section": "customers",
        "page_title": str(profile),
        "profile": profile,
        "addresses": profile.addresses.select_related("city").all(),
        "orders": profile.orders.order_by("-created_at")[:10],
    }
    return render(request, "dashboard/customers/detail.html", context)


class ContactInquiryListView(DashboardListView):
    model = ContactInquiry
    nav_section = "inquiries"
    url_basename = "inquiry"
    singular_name = "Inquiry"
    plural_name = "Inquiries"
    search_fields = ["name", "email", "message"]
    can_create = False
    can_view = True
    can_edit = False
    can_delete = True
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Email", "name": "email"},
        {"label": "Date", "name": "created_at", "type": "date"},
    ]


class ContactInquiryDeleteView(DashboardDeleteView):
    model = ContactInquiry
    nav_section = "inquiries"
    url_basename = "inquiry"
    singular_name = "Inquiry"


@dashboard_required
@require_http_methods(["GET", "POST"])
def inquiry_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Read a full inquiry message and reply to it by email.

    """
    inquiry = get_object_or_404(ContactInquiry, pk=pk)

    if request.method == "POST":
        reply_form = forms.ContactInquiryReplyForm(request.POST)
        if reply_form.is_valid():
            try:
                EmailMessage(
                    subject=reply_form.cleaned_data["subject"],
                    body=reply_form.cleaned_data["message"],
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[inquiry.email],
                ).send(fail_silently=False)
            except Exception:
                messages.error(
                    request,
                    "Could not send the reply email. Please check the email "
                    "settings and try again.",
                )
            else:
                messages.success(request, f"Reply sent to {inquiry.email}.")
                return redirect("dashboard:inquiry-detail", pk=inquiry.pk)
    else:
        reply_form = forms.ContactInquiryReplyForm(
            initial={"subject": "Re: Your Inquiry to ZAYE LENNOX"}
        )

    context = {
        "nav_section": "inquiries",
        "page_title": f"Inquiry from {inquiry.name}",
        "inquiry": inquiry,
        "reply_form": reply_form,
    }
    return render(request, "dashboard/customers/inquiry_detail.html", context)
