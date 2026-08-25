"""Clean-wheel SF-AC10/SF-AC11 acceptance for ScoreForm issue #191."""

from __future__ import annotations

import argparse
import importlib
import io
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import redirect_stdout
from importlib import metadata
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pds_core
from pds_core.routes import class_roster_path
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name

from scoreform.assignment import assignment_from_json_bytes, validate_assignment_data
from scoreform.assignment_context import AssignmentContextRef, AssignmentContextSession
from scoreform.guided_share_results import (
    ShareResultsNextStep,
    plan_share_results_readiness,
)
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.menu_share_results import launch_share_results_with_meridian
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.work_paths import initialize_scoreform_work_layout
from scoreform.workflows import write_assignment_json

SYNTHETIC_CLASS_ID = "share_acceptance_class"
SYNTHETIC_ASSIGNMENT_ID = "share_acceptance_quiz"
SYNTHETIC_STUDENT_ID = "synthetic_share_student"
SYNTHETIC_TITLE = "Synthetic Share Results Acceptance"


class AcceptanceFailure(RuntimeError):
    """Bounded installed-acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise AcceptanceFailure(f"{module_name} has no import origin.")
    return Path(module_file).resolve()


def _is_isolated_installed_origin(path: Path) -> bool:
    try:
        resolved = path.resolve()
        prefix = Path(sys.prefix).resolve()
        return (
            resolved.is_relative_to(prefix)
            and "site-packages" in {part.lower() for part in resolved.parts}
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _inputs(values: list[str]) -> Callable[[str], str]:
    iterator: Iterator[str] = iter(values)

    def read(prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration as error:
            raise AcceptanceFailure(
                f"guided workflow requested unexpected input: {prompt!r}"
            ) from error

    return read


def _synthetic_assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": SYNTHETIC_ASSIGNMENT_ID,
        "title": SYNTHETIC_TITLE,
        "question_count": 3,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    normalized = validate_assignment_data(candidate)
    if normalized is None:
        raise AcceptanceFailure("synthetic assignment failed validation.")
    return cast(dict[str, object], normalized)


def _synthetic_result(version: int) -> ScoreFormRoutedResult:
    if version == 1:
        answers = (
            ScoredAnswer(1, "A", True),
            ScoredAnswer(2, "BLANK", False),
            ScoredAnswer(3, "C", True),
        )
    elif version == 2:
        answers = (
            ScoredAnswer(1, "B", False),
            ScoredAnswer(2, "B", True),
            ScoredAnswer(3, "AMBIGUOUS", False),
        )
    else:
        raise ValueError("synthetic result version must be 1 or 2")
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=SYNTHETIC_CLASS_ID,
        assignment_id=SYNTHETIC_ASSIGNMENT_ID,
        student_id=SYNTHETIC_STUDENT_ID,
        last_name="Synthetic",
        first_name="Student",
        period="acceptance",
        page_display="manual",
        score=sum(answer.correct for answer in answers),
        total_points=3,
        answers=answers,
        source_file="plain_paper_manual_entry",
    )


def _write_native_fixture(workspace: Path) -> None:
    roster = class_roster_path(workspace, SYNTHETIC_CLASS_ID)
    roster.parent.mkdir(parents=True, exist_ok=True)
    roster.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        f"{SYNTHETIC_CLASS_ID},{SYNTHETIC_STUDENT_ID},Synthetic,Student,acceptance\n",
        encoding="utf-8",
    )
    paths = initialize_scoreform_work_layout(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    _require(
        write_assignment_json(paths.assignment_path, _synthetic_assignment()),
        "synthetic assignment could not be written.",
    )
    parsed = assignment_from_json_bytes(paths.assignment_path.read_bytes())
    _require(
        parsed["assignment_id"] == SYNTHETIC_ASSIGNMENT_ID,
        "synthetic assignment identity disagrees after write.",
    )
    first = export_scoreform_result_models(
        (_synthetic_result(1),), workspace_root=workspace
    )
    _require(
        first.succeeded and len(first.appended_attempts) == 1,
        "first synthetic result was not appended exactly once.",
    )


def _append_successor(workspace: Path) -> None:
    second = export_scoreform_result_models(
        (_synthetic_result(2),), workspace_root=workspace
    )
    _require(
        second.succeeded and len(second.appended_attempts) == 1,
        "successor synthetic result was not appended exactly once.",
    )


def _assert_no_meridian_runtime_dependency() -> None:
    requirements = tuple(Requirement(item) for item in (metadata.requires("scoreform") or ()))
    names = {canonicalize_name(item.name) for item in requirements}
    _require(
        "pds-meridian" not in names and "meridian" not in names,
        "ScoreForm metadata acquired a Meridian runtime dependency.",
    )
    for distribution_name in ("pds-meridian", "meridian"):
        try:
            metadata.version(distribution_name)
        except metadata.PackageNotFoundError:
            continue
        raise AcceptanceFailure(
            f"clean acceptance environment unexpectedly contains {distribution_name}."
        )
    imported = sorted(
        name for name in sys.modules if name.split(".", 1)[0] in {"meridian", "pds_meridian"}
    )
    _require(not imported, "guided publication imported Meridian implementation modules.")


def _verify_installed_provenance(
    workspace: Path, *, version: str, expected_core_version: str
) -> None:
    _require(not workspace.exists(), f"workspace must begin absent: {workspace}")
    _require(metadata.version("scoreform") == version, "ScoreForm version mismatch.")
    _require(
        metadata.version("pds-core") == expected_core_version,
        "PDS Core distribution version mismatch.",
    )
    _require(
        getattr(pds_core, "__version__", None) == expected_core_version,
        "PDS Core module/distribution versions disagree.",
    )
    _require(
        expected_core_version == "0.6.3",
        "SF-AC10/SF-AC11 must qualify the current Core 0.6.3 reference release.",
    )
    requirements = tuple(Requirement(item) for item in (metadata.requires("scoreform") or ()))
    core_requirements = tuple(
        item for item in requirements if canonicalize_name(item.name) == "pds-core"
    )
    _require(
        len(core_requirements) == 1
        and core_requirements[0].specifier == SpecifierSet(">=0.6,<0.7"),
        "ScoreForm Core compatibility metadata must remain pds-core>=0.6,<0.7.",
    )
    for module_name in (
        "scoreform",
        "scoreform.guided_share_results",
        "scoreform.menu_share_results",
        "scoreform.menu_assignment_tasks",
        "scoreform.assignment_context",
        "scoreform.academic_work_registration",
        "scoreform.academic_result_manifest_generation",
        "scoreform.academic_result_publication",
        "pds_core",
        "pds_core.registry_services",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )
    pip_check = _run([sys.executable, "-m", "pip", "check"], cwd=workspace.parent)
    _require(
        pip_check.returncode == 0,
        f"installed pip check failed: {pip_check.stdout} {pip_check.stderr}",
    )
    _assert_no_meridian_runtime_dependency()


def _run_guided(
    workspace: Path, session: AssignmentContextSession, responses: list[str]
) -> tuple[int, str]:
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    output = io.StringIO()
    with patch("builtins.input", _inputs(responses)), redirect_stdout(output):
        status = launch_share_results_with_meridian(
            clear_screen_fn=lambda: None,
            context_session=session,
        )
    return status, output.getvalue()


def _verify_first_publication(
    workspace: Path, session: AssignmentContextSession
) -> None:
    status, output = _run_guided(
        workspace,
        session,
        ["1", "2", "REGISTER", "GENERATE", "PUBLISH"],
    )
    _require(status == 0, "first guided publication returned nonzero.")
    for expected in (
        "Academic Work Registration",
        "Manifest revision 1",
        "Results are published through Core and available for Meridian to consume.",
    ):
        _require(expected in output, f"first publication output lacks {expected!r}.")
    for forbidden in ("Meridian imported", SYNTHETIC_STUDENT_ID, "SHA-256", "publication_id"):
        _require(forbidden not in output, f"teacher output leaked or overstated {forbidden!r}.")
    readiness = plan_share_results_readiness(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    _require(
        readiness.next_step is ShareResultsNextStep.ALREADY_CURRENT
        and readiness.registration_revision == 1
        and readiness.producer_head_revision == 1
        and readiness.core_head_revision == 1,
        "first guided publication did not reconcile to exact current state.",
    )
    _assert_no_meridian_runtime_dependency()


def _verify_successor_cancellation_and_supersession(
    workspace: Path, session: AssignmentContextSession
) -> None:
    _append_successor(workspace)
    status, cancelled = _run_guided(workspace, session, ["GENERATE", "b"])
    _require(status == 0, "successor cancellation returned nonzero.")
    for expected in (
        "Manifest revision 2 is already stored.",
        "Core publication revision 1 remains current.",
        "No supersession was written.",
    ):
        _require(expected in cancelled, f"successor cancellation output lacks {expected!r}.")
    pending = plan_share_results_readiness(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    _require(
        pending.next_step is ShareResultsNextStep.SUPERSEDE
        and pending.producer_head_revision == 2
        and pending.core_head_revision == 1
        and pending.expected_current_publication_id is not None,
        "cancelled successor did not preserve exact pending supersession state.",
    )
    predecessor_id = pending.expected_current_publication_id
    status, completed = _run_guided(workspace, session, ["SUPERSEDE"])
    _require(status == 0, "exact successor supersession returned nonzero.")
    for expected in (
        "Currently published revision: 1",
        "New producer revision: 2",
        "previous publication remains in immutable history",
        "available for Meridian to consume",
    ):
        _require(
            expected.lower() in completed.lower(),
            f"successor completion output lacks {expected!r}.",
        )
    current = plan_share_results_readiness(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    _require(
        current.next_step is ShareResultsNextStep.ALREADY_CURRENT
        and current.producer_head_revision == 2
        and current.core_head_revision == 2
        and current.core_head_publication_id != predecessor_id,
        "successor publication did not become the exact current Core head.",
    )
    _assert_no_meridian_runtime_dependency()


def verify(workspace: Path, *, version: str, expected_core_version: str) -> None:
    """Run clean installed SF-AC10/SF-AC11 publication acceptance."""
    _verify_installed_provenance(
        workspace,
        version=version,
        expected_core_version=expected_core_version,
    )
    _write_native_fixture(workspace)
    session = AssignmentContextSession()
    session.activate(
        AssignmentContextRef(SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID),
        workspace_root=workspace,
    )
    _verify_first_publication(workspace, session)
    _verify_successor_cancellation_and_supersession(workspace, session)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    args = parser.parse_args()
    try:
        verify(
            args.workspace.resolve(),
            version=args.version,
            expected_core_version=args.expected_core_version,
        )
    except AcceptanceFailure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(
        "PASS: installed Share Results with Meridian satisfies SF-AC10 and SF-AC11 "
        "without a Meridian runtime dependency."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
