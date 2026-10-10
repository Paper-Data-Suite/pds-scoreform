"""Presentation-only guard against spreadsheet formulas in human-facing CSV.

Never use this for canonical results history, source models, manifests, or JSON.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")
_FORMULA_PREFIXES = frozenset("=+-@")
# These characters can be ignored or hidden at the start of a spreadsheet cell.
_IGNORABLE_PREFIXES = frozenset("\ufeff\u200b\u200c\u200d\u2060")


def spreadsheet_safe_cell(value: T) -> T | str:
    """Prefix hazardous textual cells with an apostrophe before CSV encoding.

    Numeric and other non-string values are passed through unchanged. CSV
    quoting alone does not prevent spreadsheet formula evaluation; the extra
    leading apostrophe is intentionally part of the *exported* presentation.
    """
    if not isinstance(value, str) or not value:
        return value
    # Leading control characters are hazardous independently of a formula;
    # Excel-like importers may discard, hide, or interpret them specially.
    if ord(value[0]) < 32 or ord(value[0]) == 127:
        return "'" + value
    for character in value:
        if ord(character) < 32 or ord(character) == 127:
            return "'" + value
        if character in _FORMULA_PREFIXES:
            return "'" + value
        if character.isspace() or character in _IGNORABLE_PREFIXES:
            continue
        return value
    return value
