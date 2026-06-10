from pds_core import identifiers as core_identifiers
from pds_core.identifiers import IdentifierValidationError

# Preserve the existing ScoreForm-facing name while making pds-core authoritative.
IDENTIFIER_PATTERN = core_identifiers.IDENTIFIER_PATTERN
IDENTIFIER_RULE_MESSAGE = (
    "Allowed characters are letters, numbers, underscores, and hyphens only."
)


def is_safe_identifier(value):
    """Return True when value is a non-empty safe identifier string."""
    return core_identifiers.is_valid_identifier(value)


def validate_identifier(field_name, value, context=None):
    """Validate an identifier and print a user-facing error when unsafe."""
    label = f"{context} {field_name}" if context else field_name

    try:
        core_identifiers.validate_identifier(value, field_name)
    except IdentifierValidationError:
        if not isinstance(value, str) or not value:
            print(f"Error: {label} is empty or not a string: {value!r}")
        else:
            print(f"Error: {label} is unsafe: '{value}'. {IDENTIFIER_RULE_MESSAGE}")
        return False

    return True
