"""Write operations and business rules for the notifications app."""

from __future__ import annotations

import logging

from django.contrib.auth.models import User

from notifications.models import Notification

logger = logging.getLogger(__name__)


def send_sms(*, phone: str, message: str) -> None:
    """Dispatch an SMS — provider-agnostic stub that logs the payload."""
    logger.info("SMS to %s: %s", phone, message)


def send_email(*, email: str, subject: str, message: str) -> None:
    """Dispatch an email via Django's configured backend (console in dev, SMTP in production)."""
    from email.utils import formataddr

    from django.core.mail import send_mail
    from django.conf import settings
    from core.services import get_site_settings

    logger.info("Sending email to %s [%s]", email, subject)

    site_settings = get_site_settings()
    # Use the site's display name, not vendor_email (that's a separate inbox for
    # receiving contact inquiries). Putting an unrelated address in the display-name
    # slot of the From header is a classic spoofing pattern — providers like Gmail
    # will silently spam-filter/drop such mail even though the SMTP send "succeeds".
    display_name = site_settings.site_name or "Desert Star"
    from_email = formataddr((display_name, settings.DEFAULT_FROM_EMAIL))

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send email to %s [%s]", email, subject)
        raise

    logger.info("Email to %s [%s] handed off to SMTP backend successfully", email, subject)


def send_whatsapp(*, phone: str, message: str) -> None:
    """Dispatch a WhatsApp message — provider-agnostic stub that logs the payload."""
    logger.info("WhatsApp to %s: %s", phone, message)


def create_notification(*, user: User, title: str, body: str = "") -> Notification:
    """
    Persist an in-app notification for a user.

    Params:
        user: Recipient Django User.
        title: Notification headline.
        body: Optional full message body.
    Returns:
        Created Notification instance.
    """
    return Notification.objects.create(user=user, title=title, body=body)
