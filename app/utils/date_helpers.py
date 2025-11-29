"""Date utility functions."""

from datetime import date, datetime
from dateutil.relativedelta import relativedelta


def get_month_key(dt: date | datetime) -> str:
    """Convert date to YYYY-MM format."""
    if isinstance(dt, datetime):
        dt = dt.date()
    return dt.strftime("%Y-%m")


def parse_month_key(month_key: str) -> date:
    """Parse YYYY-MM string to first day of month."""
    return datetime.strptime(month_key, "%Y-%m").date()


def get_next_month(dt: date) -> date:
    """Get first day of next month."""
    return dt + relativedelta(months=1, day=1)


def get_previous_month(dt: date) -> date:
    """Get first day of previous month."""
    return dt - relativedelta(months=1, day=1)


def get_month_range(start_date: date, months: int) -> list[date]:
    """Get list of month start dates for given range."""
    return [start_date + relativedelta(months=i, day=1) for i in range(months)]
