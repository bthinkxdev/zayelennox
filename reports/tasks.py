"""Celery tasks for the reports app."""

from __future__ import annotations

from datetime import date

from celery import shared_task

from reports.services import aggregate_daily_reports


@shared_task(name="reports.tasks.aggregate_daily_reports")
def aggregate_daily_reports_task(report_date_iso: str | None = None) -> dict[str, int]:
    """
    Populate pre-aggregated report tables for a single day.

    """
    report_date = date.fromisoformat(report_date_iso) if report_date_iso else None
    return aggregate_daily_reports(report_date=report_date)
