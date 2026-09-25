"""Reusable file validators for the catalog app."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


@deconstructible
class MaxFileSizeValidator:
    """
    Rejects an uploaded file over ``max_mb`` megabytes.

    States both the file's actual size and the limit in the error message,
    so the vendor knows exactly how far over they are rather than just "too big".
    """

    def __init__(self, max_mb: int):
        self.max_mb = max_mb
        self.max_bytes = max_mb * 1024 * 1024

    def __call__(self, value):
        size = getattr(value, "size", None)
        if size is not None and size > self.max_bytes:
            actual_mb = size / (1024 * 1024)
            raise ValidationError(
                "This file is %.1f MB — the maximum allowed size is %d MB." % (actual_mb, self.max_mb)
            )

    def __eq__(self, other):
        return isinstance(other, MaxFileSizeValidator) and self.max_mb == other.max_mb
