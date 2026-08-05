"""Domain exceptions for the shipping app."""

from __future__ import annotations


class ShiprocketAPIError(Exception):
    """Wrapped errors from the Shiprocket API or network layer."""
