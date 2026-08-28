"""Domain exceptions for the payments app."""

from __future__ import annotations


class InvalidPaymentStatusTransitionError(Exception):
    """Raised when a payment status change is not allowed."""
