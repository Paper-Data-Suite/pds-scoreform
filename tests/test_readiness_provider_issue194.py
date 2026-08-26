"""ScoreForm issue #194 readiness semantics and noninterference tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.module_operations import (
    ModuleOperationsContractError,
    ModuleOperationsRequest,
)
from pds_core.routes import class_roster_path, classes_dir
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)

from scoreform.assignment_context import AssignmentContextRef, AssignmentContextSession
from scoreform.attention_provider import evaluate_scoreform_attention
from scoreform.diagnostic_events import build_diagnostic_event, record_diagnostic_event
from scoreform.readiness_provider import evaluate_scoreform_readiness
from scoreform.scan_review_details import scoreform_failure_details

CLASS_ID = "english10_p2"
OTHER_CLASS_ID = "english12_p4"
PRIVATE_STUDENT_ID = "private_student_readiness_sentinel"
PRIVATE_FAILURE = "private readiness failure detail sentinel"


def _write_valid_roster(root: Path, class_id: str = CLASS_ID) -> Path:
    path = class_roster_path(root, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        f"{class_id},student1,Student,One,2\n",
        encoding="utf-8",
    )
    return path


def _make_directory_symlink(link: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"directory symlink unavailable in this environment: {error}")


def _scan_failure() -> RoutingFailureMetadata:
    return RoutingFailureMetadata(
        schema_version="2",
        failure_id="readiness_attention_failure",
        scope="page",
        stage="attempt_assembly",
        created_at="2026-08-25T20:00:00+00:00",
        failure_category="page_conflict",
        failure_message=PRIVATE_FAILURE,
        source_filename="private_readiness_scan.pdf",
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details=scoreform_failure_details(
            origin="attempt_assembly",
            category="missing_pages",
            context={
                "observed_identity": {
                    "class_id": CLASS_ID,
                    "assignment_id": "quiz_one",
                    "student_id": PRIVATE_STUDENT_ID,
                },
                "expected_logical_pages": [1, 2],
                "missing_logical_pages": [2],
            },
        ),
    )


def test_no_workspace_is_unavailable() -> None:
    report = evaluate_scoreform_readiness(ModuleOperationsRequest())

    assert report.evaluation == "unavailable"
    assert report.ready is None
    assert tuple(notice.code for notice in report.notices) == (
        "scoreform_readiness_unavailable",
    )


def test_missing_workspace_is_unavailable_and_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "must-remain-absent"

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=missing)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None
    assert not missing.exists()


def test_valid_empty_workspace_is_ready_without_creating_state(tmp_path: Path) -> None:
    before = tuple(tmp_path.iterdir())

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is True
    assert report.notices == ()
    assert tuple(tmp_path.iterdir()) == before


def test_non_directory_workspace_is_known_not_ready(tmp_path: Path) -> None:
    root = tmp_path / "workspace-file"
    root.write_text("not a workspace", encoding="utf-8")

    report = evaluate_scoreform_readiness(ModuleOperationsRequest(workspace_root=root))

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == "scoreform_workspace_not_ready"


def test_linked_workspace_is_unavailable(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "linked-workspace"
    _make_directory_symlink(link, target)

    report = evaluate_scoreform_readiness(ModuleOperationsRequest(workspace_root=link))

    assert report.evaluation == "unavailable"
    assert report.ready is None


def test_authoritatively_nonwritable_workspace_is_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scoreform.readiness_provider.inspect_workspace_root",
        lambda root: SimpleNamespace(
            root=Path(root),
            exists=True,
            is_dir=True,
            is_writable=False,
        ),
    )

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == "scoreform_workspace_not_ready"



def test_unsafe_class_identifier_is_rejected_by_core_request_contract(
    tmp_path: Path,
) -> None:
    with pytest.raises(ModuleOperationsContractError):
        ModuleOperationsRequest(workspace_root=tmp_path, class_id="../escape")

def test_exact_existing_class_with_valid_roster_is_ready(tmp_path: Path) -> None:
    _write_valid_roster(tmp_path)

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is True
    assert report.notices == ()
    assert not (tmp_path / "classes" / CLASS_ID / "modules" / "scoreform").exists()


def test_exact_missing_class_is_not_ready_without_substitution(tmp_path: Path) -> None:
    _write_valid_roster(tmp_path, OTHER_CLASS_ID)

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == "scoreform_class_not_ready"
    assert not (classes_dir(tmp_path) / CLASS_ID).exists()


def test_existing_class_without_roster_is_not_ready(tmp_path: Path) -> None:
    (classes_dir(tmp_path) / CLASS_ID).mkdir(parents=True)

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == "scoreform_class_not_ready"


def test_invalid_authoritative_roster_is_not_ready_and_private(tmp_path: Path) -> None:
    roster = class_roster_path(tmp_path, CLASS_ID)
    roster.parent.mkdir(parents=True)
    roster.write_text(
        f"bad_header\n{PRIVATE_STUDENT_ID}\n{PRIVATE_FAILURE}\n",
        encoding="utf-8",
    )

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    rendered = repr(report)
    assert PRIVATE_STUDENT_ID not in rendered
    assert PRIVATE_FAILURE not in rendered
    assert str(tmp_path) not in rendered



def test_uninspectable_roster_exception_detail_is_not_shared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_valid_roster(tmp_path)
    monkeypatch.setattr(
        "scoreform.readiness_provider.load_class_roster",
        lambda root, class_id: (_ for _ in ()).throw(OSError(PRIVATE_FAILURE)),
    )

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None
    assert PRIVATE_FAILURE not in repr(report)

def test_linked_exact_class_is_unavailable(tmp_path: Path) -> None:
    shared = classes_dir(tmp_path)
    shared.mkdir(parents=True)
    target = tmp_path / "outside-class"
    link = shared / CLASS_ID
    _make_directory_symlink(link, target)

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None


def test_active_school_year_does_not_invent_readiness_semantics(tmp_path: Path) -> None:
    without_year = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )
    with_year = evaluate_scoreform_readiness(
        ModuleOperationsRequest(
            workspace_root=tmp_path,
            active_school_year="2026-2027",
        )
    )

    assert with_year == without_year


def test_readiness_is_true_while_attention_is_nonempty(tmp_path: Path) -> None:
    _write_valid_roster(tmp_path)
    write_routing_failure_metadata(tmp_path, _scan_failure())
    request = ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)

    readiness = evaluate_scoreform_readiness(request)
    attention = evaluate_scoreform_attention(request)

    assert readiness.ready is True
    assert attention.evaluation == "evaluated"
    assert attention.summaries != ()


def test_readiness_does_not_call_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scoreform.attention_provider.evaluate_scoreform_attention",
        lambda request: (_ for _ in ()).throw(AssertionError("attention was called")),
    )

    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.ready is True


def test_diagnostic_history_does_not_change_readiness(tmp_path: Path) -> None:
    request = ModuleOperationsRequest(workspace_root=tmp_path)
    baseline = evaluate_scoreform_readiness(request)
    event = build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code="qr_missing",
        exception=RuntimeError(PRIVATE_FAILURE),
    )
    record_diagnostic_event(tmp_path, event)
    diagnostic_inventory = tuple(sorted(tmp_path.rglob("*")))

    after = evaluate_scoreform_readiness(request)

    assert after == baseline
    assert tuple(sorted(tmp_path.rglob("*"))) == diagnostic_inventory


def test_recent_assignment_context_does_not_change_or_mutate_readiness(
    tmp_path: Path,
) -> None:
    request = ModuleOperationsRequest(workspace_root=tmp_path)
    baseline = evaluate_scoreform_readiness(request)
    session = AssignmentContextSession()
    ref = AssignmentContextRef(CLASS_ID, "quiz_one")
    session.activate(ref, workspace_root=tmp_path)
    before_active = session.active
    before_recent = session.recent

    after = evaluate_scoreform_readiness(request)

    assert after == baseline
    assert session.active == before_active
    assert session.recent == before_recent


def test_readiness_is_silent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = evaluate_scoreform_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    captured = capsys.readouterr()
    assert report.ready is True
    assert captured.out == ""
    assert captured.err == ""
