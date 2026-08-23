"""Session-scoped recent/active assignment context for ScoreForm."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pds_core.identifiers import validate_identifier

MAX_RECENT_ASSIGNMENTS = 5


@dataclass(frozen=True, slots=True)
class AssignmentContextRef:
    """Minimal exact identity for one managed ScoreForm assignment."""

    class_id: str
    assignment_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "class_id",
            validate_identifier(self.class_id, "class_id"),
        )
        object.__setattr__(
            self,
            "assignment_id",
            validate_identifier(self.assignment_id, "assignment_id"),
        )


@dataclass(slots=True)
class AssignmentContextSession:
    """One interactive process's identity-only assignment continuity state."""

    _active: AssignmentContextRef | None = None
    _recent: list[AssignmentContextRef] = field(default_factory=list)
    _workspace_root: Path | None = None

    @property
    def active(self) -> AssignmentContextRef | None:
        return self._active

    @property
    def recent(self) -> tuple[AssignmentContextRef, ...]:
        return tuple(self._recent)

    @property
    def is_workspace_bound(self) -> bool:
        return self._workspace_root is not None

    def bind_workspace(self, workspace_root: str | Path) -> bool:
        """Bind to one workspace; clear context if the workspace changed."""
        resolved = Path(workspace_root).expanduser().resolve()
        if self._workspace_root is None:
            self._workspace_root = resolved
            return False
        if self._workspace_root == resolved:
            return False

        self._workspace_root = resolved
        self._active = None
        self._recent.clear()
        return True

    def activate(
        self,
        ref: AssignmentContextRef,
        *,
        workspace_root: str | Path,
    ) -> None:
        """Make one validated identity active and move it to the MRU front."""
        self.bind_workspace(workspace_root)
        self._active = ref
        self._recent = [candidate for candidate in self._recent if candidate != ref]
        self._recent.insert(0, ref)
        del self._recent[MAX_RECENT_ASSIGNMENTS:]

    def clear_active(self) -> None:
        self._active = None

    def clear_recent(self) -> None:
        self._recent.clear()

    def discard(self, ref: AssignmentContextRef) -> None:
        """Remove a proven-stale identity from active/recent context."""
        if self._active == ref:
            self._active = None
        self._recent = [candidate for candidate in self._recent if candidate != ref]


@dataclass(frozen=True, slots=True)
class AssignmentContextResolution:
    """Ephemeral result of resolving one context reference canonically."""

    ref: AssignmentContextRef
    record: dict[str, Any] | None = None
    stale_reason: str | None = None
    workspace_changed: bool = False

    @property
    def is_valid(self) -> bool:
        return self.record is not None and self.stale_reason is None


def assignment_context_ref_from_record(record: dict[str, Any]) -> AssignmentContextRef:
    """Build the minimal context identity from one canonical discovery record."""
    return AssignmentContextRef(
        class_id=str(record["class_id"]),
        assignment_id=str(record["assignment_id"]),
    )


def _current_workspace_root(workspace_root: str | Path | None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).expanduser().resolve()

    from scoreform import workspace

    return Path(workspace.get_scoreform_workspace_root()).expanduser().resolve()


def resolve_assignment_context_ref(
    session: AssignmentContextSession,
    ref: AssignmentContextRef,
    *,
    workspace_root: str | Path | None = None,
) -> AssignmentContextResolution:
    """Resolve a context identity through current canonical ScoreForm discovery."""
    root = _current_workspace_root(workspace_root)
    if session.bind_workspace(root):
        return AssignmentContextResolution(
            ref=ref,
            stale_reason="The workspace changed; prior assignment context was cleared.",
            workspace_changed=True,
        )

    from scoreform import workflows

    try:
        classes = workflows.discover_class_rosters(workspace_root=root)
    except (OSError, ValueError) as exc:
        session.discard(ref)
        return AssignmentContextResolution(
            ref=ref,
            stale_reason=f"The class context could not be validated: {exc}",
        )

    if not any(record.get("class_id") == ref.class_id for record in classes):
        session.discard(ref)
        return AssignmentContextResolution(
            ref=ref,
            stale_reason=f"Class '{ref.class_id}' is no longer available.",
        )

    try:
        assignments = workflows.discover_class_assignments(
            ref.class_id,
            workspace_root=root,
        )
    except (OSError, ValueError) as exc:
        session.discard(ref)
        return AssignmentContextResolution(
            ref=ref,
            stale_reason=f"The assignment context could not be validated: {exc}",
        )

    for record in assignments:
        if record.get("assignment_id") == ref.assignment_id:
            return AssignmentContextResolution(ref=ref, record=record)

    session.discard(ref)
    return AssignmentContextResolution(
        ref=ref,
        stale_reason=(
            f"Assignment '{ref.assignment_id}' is no longer available in "
            f"class '{ref.class_id}'."
        ),
    )


def resolve_active_assignment_context(
    session: AssignmentContextSession,
    *,
    workspace_root: str | Path | None = None,
) -> AssignmentContextResolution | None:
    """Resolve the current active identity, if any, without guessing a target."""
    ref = session.active
    if ref is None:
        return None
    return resolve_assignment_context_ref(
        session,
        ref,
        workspace_root=workspace_root,
    )


def resolve_recent_assignment_contexts(
    session: AssignmentContextSession,
    *,
    workspace_root: str | Path | None = None,
) -> tuple[AssignmentContextResolution, ...]:
    """Return only currently valid recent assignments and prune stale entries."""
    if not session.recent:
        return ()

    root = _current_workspace_root(workspace_root)
    if session.bind_workspace(root):
        return ()

    resolved: list[AssignmentContextResolution] = []
    for ref in tuple(session.recent):
        outcome = resolve_assignment_context_ref(
            session,
            ref,
            workspace_root=root,
        )
        if outcome.is_valid:
            resolved.append(outcome)
    return tuple(resolved)


def reconcile_session_workspace(session: AssignmentContextSession) -> bool:
    """Clear bound context if the configured workspace changed during this process."""
    if not session.is_workspace_bound:
        return False
    root = _current_workspace_root(None)
    return session.bind_workspace(root)
