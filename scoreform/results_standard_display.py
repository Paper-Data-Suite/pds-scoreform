"""Fail-soft teacher-facing Standard display projection for Results Analysis."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pds_core.standards import StandardsReadError, StandardsValidationError
from pds_core.standards_selection import (
    load_standards_for_selection,
    resolve_standard_selection,
)


@dataclass(frozen=True, slots=True)
class StandardDisplayProjectionItem:
    """Display metadata for one authoritative durable Standard ID."""

    standard_id: str
    display_label: str
    resolved: bool

    def __post_init__(self) -> None:
        if not isinstance(self.standard_id, str) or not self.standard_id:
            raise ValueError("standard_id must be a nonempty string.")
        if not isinstance(self.display_label, str) or not self.display_label:
            raise ValueError("display_label must be a nonempty string.")
        if not isinstance(self.resolved, bool):
            raise TypeError("resolved must be Boolean.")


@dataclass(frozen=True, slots=True)
class ResultsStandardsProjection:
    """Immutable display projection that never replaces durable Standard identity."""

    items: tuple[StandardDisplayProjectionItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("items must be a tuple.")
        if any(
            not isinstance(item, StandardDisplayProjectionItem)
            for item in self.items
        ):
            raise TypeError(
                "items must contain StandardDisplayProjectionItem values."
            )
        standard_ids = tuple(item.standard_id for item in self.items)
        if len(standard_ids) != len(set(standard_ids)):
            raise ValueError("items must not repeat Standard IDs.")

    @property
    def standard_ids(self) -> tuple[str, ...]:
        """Return durable Standard IDs in projection order."""
        return tuple(item.standard_id for item in self.items)

    def label_for(self, standard_id: str) -> str:
        """Return the projected label, falling back to durable identity."""
        if not isinstance(standard_id, str) or not standard_id:
            raise ValueError("standard_id must be a nonempty string.")
        for item in self.items:
            if item.standard_id == standard_id:
                return item.display_label
        return standard_id

    def resolved_for(self, standard_id: str) -> bool:
        """Return whether current Core metadata resolved this Standard ID."""
        if not isinstance(standard_id, str) or not standard_id:
            raise ValueError("standard_id must be a nonempty string.")
        for item in self.items:
            if item.standard_id == standard_id:
                return item.resolved
        return False


EMPTY_RESULTS_STANDARDS_PROJECTION = ResultsStandardsProjection(())


def _normalize_standard_ids(
    standard_ids: Iterable[str],
) -> tuple[str, ...]:
    if isinstance(standard_ids, (str, bytes)):
        raise TypeError("standard_ids must be an iterable of strings.")
    try:
        materialized = tuple(standard_ids)
    except TypeError as error:
        raise TypeError("standard_ids must be an iterable of strings.") from error

    for standard_id in materialized:
        if not isinstance(standard_id, str) or not standard_id:
            raise ValueError("standard_ids must contain nonempty strings.")
    return tuple(sorted(set(materialized)))


def fallback_results_standards_projection(
    standard_ids: Iterable[str],
) -> ResultsStandardsProjection:
    """Build an ID-only projection without reading workspace metadata."""
    normalized = _normalize_standard_ids(standard_ids)
    return ResultsStandardsProjection(
        tuple(
            StandardDisplayProjectionItem(
                standard_id=standard_id,
                display_label=standard_id,
                resolved=False,
            )
            for standard_id in normalized
        )
    )


def resolve_results_standards_projection(
    standard_ids: Iterable[str],
    *,
    workspace_root: str | Path | None,
) -> ResultsStandardsProjection:
    """Resolve Core display labels without making Results Analysis depend on them.

    Missing, unreadable, invalid, inactive, or unknown current metadata never
    changes calculation or durable identity. Inactive definitions still resolve
    through Core's display formatter and retain Core's ``[inactive]`` marker.
    Unknown IDs and unreadable libraries fall back to the durable Standard ID.
    """
    normalized = _normalize_standard_ids(standard_ids)
    fallback = fallback_results_standards_projection(normalized)
    if not normalized or workspace_root is None:
        return fallback

    try:
        library = load_standards_for_selection(workspace_root)
    except (StandardsReadError, StandardsValidationError, OSError):
        return fallback

    projected: list[StandardDisplayProjectionItem] = []
    for standard_id in normalized:
        try:
            selection = resolve_standard_selection(library, standard_id)
        except StandardsValidationError:
            projected.append(
                StandardDisplayProjectionItem(
                    standard_id=standard_id,
                    display_label=standard_id,
                    resolved=False,
                )
            )
            continue

        projected.append(
            StandardDisplayProjectionItem(
                standard_id=standard_id,
                display_label=selection.label,
                resolved=True,
            )
        )

    return ResultsStandardsProjection(tuple(projected))
