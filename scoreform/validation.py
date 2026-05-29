import re


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
IDENTIFIER_RULE_MESSAGE = (
    "Allowed characters are letters, numbers, underscores, and hyphens only."
)


def is_safe_identifier(value):
    """Return True when value is a non-empty safe identifier string."""
    return isinstance(value, str) and bool(IDENTIFIER_PATTERN.fullmatch(value))


def validate_identifier(field_name, value, context=None):
    """Validate an identifier and print a user-facing error when unsafe."""
    label = f"{context} {field_name}" if context else field_name

    if not isinstance(value, str) or not value:
        print(f"Error: {label} is empty or not a string: {value!r}")
        return False

    if not IDENTIFIER_PATTERN.fullmatch(value):
        print(f"Error: {label} is unsafe: '{value}'. {IDENTIFIER_RULE_MESSAGE}")
        return False

    return True
