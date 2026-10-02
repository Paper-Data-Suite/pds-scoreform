"""Fail-soft teacher-facing Standard display projection for Results Analysis."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from pds_core.standards import StandardsReadError, StandardsValidationError
from pds_core.standards_selection import (
    list_standards_for_profile_selection,
    load_standards_for_selection,
    resolve_standard_selection,
)


class _StandardIdItem(Protocol):
    @property
    def standard_id(self) -> str:
        """Return the authoritative durable Standard ID."""
        ...


StandardItemT = TypeVar("StandardItemT", bound=_StandardIdItem)


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
        """Return durable Standard IDs in frozen presentation order."""
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


def _normalize_profile_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("standards_profile_id must be a string or None.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(
            "standards_profile_id must be nonempty when provided."
        )
    return normalized


def fallback_results_standards_projection(
    standard_ids: Iterable[str],
) -> ResultsStandardsProjection:
    """Build a lexical ID-only projection without reading workspace metadata."""
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


def _profile_ordered_ids(
    standard_ids: tuple[str, ...],
    *,
    library: object,
    standards_profile_id: str | None,
) -> tuple[str, ...]:
    if standards_profile_id is None:
        return standard_ids

    try:
        profile_items = list_standards_for_profile_selection(
            library,  # type: ignore[arg-type]
            standards_profile_id,
            active=None,
        )
    except StandardsValidationError:
        return standard_ids

    requested = set(standard_ids)
    profile_order = tuple(
        item.standard_id
        for item in profile_items
        if item.standard_id in requested
    )
    represented = set(profile_order)
    lexical_tail = tuple(
        standard_id
        for standard_id in standard_ids
        if standard_id not in represented
    )
    return profile_order + lexical_tail


def resolve_results_standards_projection(
    standard_ids: Iterable[str],
    *,
    workspace_root: str | Path | None,
    standards_profile_id: str | None = None,
) -> ResultsStandardsProjection:
    """Resolve current Core labels and optional profile presentation order.

    Durable Standard IDs remain authoritative. When the assignment's current
    profile resolves, aligned profile members are presented in Core profile
    order. Any aligned IDs not represented by that current profile follow in
    deterministic lexical ID order.

    Missing or unreadable library metadata, an unavailable/stale profile, or an
    unknown Standard ID never changes calculation or durable identity. Label
    resolution remains independent of profile resolution.
    """
    normalized = _normalize_standard_ids(standard_ids)
    profile_id = _normalize_profile_id(standards_profile_id)
    fallback = fallback_results_standards_projection(normalized)
    if not normalized or workspace_root is None:
        return fallback

    try:
        library = load_standards_for_selection(workspace_root)
    except (StandardsReadError, StandardsValidationError, OSError):
        return fallback

    ordered_ids = _profile_ordered_ids(
        normalized,
        library=library,
        standards_profile_id=profile_id,
    )

    projected: list[StandardDisplayProjectionItem] = []
    for standard_id in ordered_ids:
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


def order_standard_items(
    items: Iterable[StandardItemT],
    standard_display: ResultsStandardsProjection,
) -> tuple[StandardItemT, ...]:
    """Return Standard-bearing items in the frozen presentation order."""
    if not isinstance(standard_display, ResultsStandardsProjection):
        raise TypeError(
            "standard_display must be a ResultsStandardsProjection."
        )
    if isinstance(items, (str, bytes)):
        raise TypeError("items must be an iterable of Standard-bearing values.")

    try:
        materialized = tuple(items)
    except TypeError as error:
        raise TypeError(
            "items must be an iterable of Standard-bearing values."
        ) from error

    by_standard_id: dict[str, StandardItemT] = {}
    for item in materialized:
        standard_id = getattr(item, "standard_id", None)
        if not isinstance(standard_id, str) or not standard_id:
            raise TypeError(
                "items must expose a nonempty string standard_id."
            )
        if standard_id in by_standard_id:
            raise ValueError("items must not repeat Standard IDs.")
        by_standard_id[standard_id] = item

    ordered: list[StandardItemT] = []
    used: set[str] = set()
    for standard_id in standard_display.standard_ids:
        selected = by_standard_id.get(standard_id)
        if selected is None:
            continue
        ordered.append(selected)
        used.add(standard_id)

    for standard_id in sorted(set(by_standard_id) - used):
        ordered.append(by_standard_id[standard_id])

    return tuple(ordered)
