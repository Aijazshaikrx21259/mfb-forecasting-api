"""Input validation utilities."""

import re


def validate_item_id(item_id: str) -> bool:
    """Validate item ID format."""
    # Allow alphanumeric, hyphens, underscores
    pattern = r'^[A-Za-z0-9_-]+$'
    return bool(re.match(pattern, item_id)) and len(item_id) <= 50


def validate_horizon(horizon: int) -> bool:
    """Validate forecast horizon."""
    return 1 <= horizon <= 12


def sanitize_user_input(text: str, max_length: int = 1000) -> str:
    """Sanitize user input text."""
    # Remove potentially dangerous characters
    text = text.strip()
    text = re.sub(r'[<>]', '', text)  # Remove angle brackets
    return text[:max_length]


def validate_email(email: str) -> bool:
    """Basic email validation."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))
