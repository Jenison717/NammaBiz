import re
from decimal import Decimal, InvalidOperation


def valid_email(value):
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", (value or "").strip()))


def valid_password(value):
    return isinstance(value, str) and len(value) >= 10 and len(value) <= 128


def positive_amount(value, optional=False):
    if optional and not (value or "").strip():
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        return None
    return amount if amount.is_finite() and amount > 0 else None
