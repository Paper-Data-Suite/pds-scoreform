from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
import qrcode
from pds_core.module_dispatch import (
    RouteDispatchFailure,
    RouteDispatchRequest,
    RouteDispatchSuccess,
)
from pds_core.module_profiles import ModuleProfile, ModuleRegistry
from pds_core.route_registrations import (
    resolve_route_registration,
    write_route_registration,
)
from pds_core.routing_models import (
    ModuleRecordRef,
    ModuleWorkRef,
    RouteLocator,
    RouteRegistration,
)
from pds_core.scan_retention import retain_source_scan

from scoreform import pds2_scan_dispatch as dispatch_module
from scoreform import scoring
from scoreform.module_errors import (
    ScoreFormDispatchIntegrationError,
    ScoreFormQrUnreadableError,
    ScoreFormRetainedPageError,
    ScoreFormScanPreflightError,
)
from scoreform.page_scoring import ScoredAnswer, ScoreFormPageDispatchResult
from scoreform.pds2_scan_dispatch import (
    Pds2ScanDispatchResult,
    Pds2ScanPageOutcome,
    QrPayloadDetectionResult,
    build_scoreform_scan_registry,
    dispatch_retained_scan,
    format_pds2_dispatch_summary,
    process_pds2_scan,
    validate_pds2_scan_source,
)
from scoreform.pds_module import get_module_profile
from scoreform.scoring import QrDiagnosticWriteResult


def _qr(path: Path, payload: str) -> Path:
    image = qrcode.make(payload)
    image.save(path)
    return path


def _profile(module_id: str, result: object) -> ModuleProfile:
    return ModuleProfile(
        module_id=module_id,
        display_name=module_id.title(),
        supported_core_routing_contract_versions=frozenset({"1"}),
        supported_qr_schemas=frozenset({"PDS2"}),
        supported_route_registration_schema_versions=frozenset({"1"}),
        dispatchable_route_statuses=frozenset({"active"}),
        route_handler=lambda *_args: result,
    )


def _locator(module_id: str, route_digit: str = "1") -> RouteLocator:
    return RouteLocator(
        "PDS2",
        ModuleWorkRef(module_id, "class1", "quiz1"),
        "rt_" + route_digit * 32,
    )


def _registration(tmp_path: Path, locator: RouteLocator):
    registration = RouteRegistration(
        "1",
        locator,
        ModuleRecordRef(locator.module_id, "fake_page", "rec_" + locator.route_id[3:], "1"),
        "2026-01-01T00:00:00+00:00",
        "active",
        "Test registration",
        {},
    )
    write_route_registration(tmp_path, registration)
    return resolve_route_registration(tmp_path, locator)


def _retained(tmp_path: Path):
    source = tmp_path / "incoming.png"
    assert cv2.imwrite(str(source), np.full((80, 80, 3), 255, np.uint8))
    return retain_source_scan(tmp_path, source)


def _retained_pdf(tmp_path: Path):
    source = tmp_path / "incoming.pdf"
    source.write_bytes(b"synthetic retained PDF")
    return retain_source_scan(tmp_path, source)


def _page(retained, locator: RouteLocator, number: int) -> Pds2ScanPageOutcome:
    request = RouteDispatchRequest(locator, retained, number)
    return Pds2ScanPageOutcome(
        number,
        raw_payload_text=(
            f"PDS2|m={locator.module_id}|c={locator.class_id}|"
            f"w={locator.work_id}|r={locator.route_id}"
        ),
        locator=locator,
        dispatch_request=request,
    )


def _scoreform_result(resolution, retained, source_page_number):
    return ScoreFormPageDispatchResult(
        route_id=resolution.locator.route_id,
        page_id="pg_" + "1" * 32,
        issuance_id="iss_" + "2" * 32,
        generation_id="gen_" + "3" * 32,
        artifact_id="art_" + "4" * 32,
        class_id=resolution.locator.class_id,
        assignment_id=resolution.locator.work_id,
        student_id="student1",
        logical_page=1,
        total_pages=1,
        question_start=1,
        question_end=1,
        layout_id="standard_15q_abcd_v1",
        score=0,
        total_points=1,
        answers=(ScoredAnswer(1, "BLANK", False),),
        source_scan_id=retained.source_scan_id,
        source_page_number=source_page_number,
        retained_source_relative_path=retained.retained_source_relative_path,
        source_sha256=retained.source_sha256,
        diagnostic_paths=(),
    )


def test_production_registry_builder_returns_fresh_installed_registries() -> None:
    first = build_scoreform_scan_registry()
    second = build_scoreform_scan_registry()
    assert first is not second
    assert first.require("scoreform").module_id == "scoreform"


def test_active_scan_preflight_rejects_bmp(tmp_path: Path) -> None:
    source = tmp_path / "scan.bmp"
    source.write_bytes(b"bmp")
    try:
        validate_pds2_scan_source(source)
    except ScoreFormScanPreflightError as error:
        assert "Unsupported" in str(error)
    else:
        raise AssertionError("BMP unexpectedly passed active PDS2 preflight")


def test_unknown_module_is_preserved_as_core_dispatch_failure(tmp_path: Path) -> None:
    payload = (
        "PDS2|m=missing|c=class1|w=quiz1|"
        "r=rt_10000000000000000000000000000000"
    )
    source = _qr(tmp_path / "unknown.png", payload)
    registry = ModuleRegistry((get_module_profile(),))

    result = process_pds2_scan(source, workspace_root=tmp_path, registry=registry)

    assert result.retained_source is not None
    assert result.pages[0].raw_payload_text == payload
    assert result.pages[0].locator is not None
    assert isinstance(result.pages[0].dispatch_outcome, RouteDispatchFailure)
    assert result.dispatch_failure_count == 1
    assert result.zero_success
    assert result.exit_code() == 1


def test_foreign_success_remains_opaque_and_counts_as_success(
    tmp_path: Path, monkeypatch
) -> None:
    payload = (
        f"PDS2|r=rt_{'2' * 32}|w=quiz1|"
        "c=class1|m=other"
    )
    source = _qr(tmp_path / "other.png", payload)
    opaque = object()
    foreign = _profile("other", opaque)
    registry = ModuleRegistry((get_module_profile(), foreign))
    resolution = _registration(tmp_path, _locator("other", "2"))

    def dispatch(_root, _registry, requests):
        request = tuple(requests)[0]
        return (RouteDispatchSuccess(request, foreign, resolution, opaque),)

    monkeypatch.setattr("scoreform.pds2_scan_dispatch.dispatch_routes", dispatch)
    result = process_pds2_scan(source, workspace_root=tmp_path, registry=registry)

    outcome = result.pages[0].dispatch_outcome
    assert isinstance(outcome, RouteDispatchSuccess)
    assert outcome.module_result is opaque
    assert result.other_module_success_count == 1
    assert result.complete_success
    assert result.exit_code() == 0


@pytest.mark.parametrize(
    "payload",
    (
        "PDS1|module=scoreform|class=class1",
        "OMR1|class=class1|student=1001",
        "OTHER|opaque=payload",
    ),
)
def test_unsupported_payload_is_preserved_without_locator_or_request(
    tmp_path: Path,
    payload: str,
) -> None:
    source = _qr(tmp_path / "unsupported.png", payload)
    registry = ModuleRegistry((get_module_profile(),))

    result = process_pds2_scan(source, workspace_root=tmp_path, registry=registry)

    page = result.pages[0]
    assert page.raw_payload_text == payload
    assert page.locator is None
    assert page.dispatch_request is None
    assert page.dispatch_outcome is None
    assert page.failure_stage == "payload_parsing"
    assert not (tmp_path / "classes").exists()
    assert not tuple(tmp_path.rglob("results.csv"))


def test_explicit_registry_failure_happens_before_retention(tmp_path: Path) -> None:
    source = _qr(
        tmp_path / "scan.png",
        "PDS2|m=scoreform|c=class1|w=quiz1|"
        "r=rt_30000000000000000000000000000000",
    )
    result = process_pds2_scan(
        source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((_profile("other", object()),)),
    )
    assert result.retained_source is None
    assert result.file_error is not None
    assert not (tmp_path / "scans").exists()


def test_deleted_retained_file_returns_file_error_with_exact_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    source = _qr(
        tmp_path / "scan.png",
        "PDS2|m=scoreform|c=class1|w=quiz1|r=" + "rt_" + "4" * 32,
    )
    actual_retain = retain_source_scan
    captured = []

    def retain_then_delete(root, selected):
        retained = actual_retain(root, selected)
        captured.append(retained)
        retained.retained_source_path.unlink()
        return retained

    monkeypatch.setattr(dispatch_module, "retain_source_scan", retain_then_delete)
    result = process_pds2_scan(
        source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((get_module_profile(),)),
    )
    assert result.retained_source is captured[0]
    assert result.file_error is not None
    assert result.pages == ()


def test_invalid_retained_provenance_is_returned_not_raised(
    tmp_path: Path, monkeypatch
) -> None:
    source = _qr(
        tmp_path / "scan.png",
        "PDS2|m=scoreform|c=class1|w=quiz1|r=" + "rt_" + "5" * 32,
    )
    actual_retain = retain_source_scan
    captured = []

    def forge(root, selected):
        retained = actual_retain(root, selected)
        forged = replace(retained, source_filename="../scan.png")
        captured.append(forged)
        return forged

    monkeypatch.setattr(dispatch_module, "retain_source_scan", forge)
    result = process_pds2_scan(
        source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((get_module_profile(),)),
    )
    assert result.retained_source is captured[0]
    assert result.file_error is not None
    assert captured[0].retained_source_path.exists()


def test_page_count_failure_preserves_retained_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    source = _qr(
        tmp_path / "scan.png",
        "PDS2|m=scoreform|c=class1|w=quiz1|r=" + "rt_" + "6" * 32,
    )
    captured = []
    actual_retain = retain_source_scan

    def retain(root, selected):
        retained = actual_retain(root, selected)
        captured.append(retained)
        return retained

    monkeypatch.setattr(dispatch_module, "retain_source_scan", retain)
    monkeypatch.setattr(
        dispatch_module,
        "retained_source_page_count",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ScoreFormRetainedPageError("page count failed")
        ),
    )
    result = process_pds2_scan(
        source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((get_module_profile(),)),
    )
    assert result.retained_source is captured[0]
    assert result.file_error is not None
    assert captured[0].retained_source_path.exists()


def test_registry_invalidated_after_retention_returns_result(
    tmp_path: Path, monkeypatch
) -> None:
    source = _qr(
        tmp_path / "scan.png",
        "PDS2|m=scoreform|c=class1|w=quiz1|r=" + "rt_" + "7" * 32,
    )
    registry = ModuleRegistry((get_module_profile(),))
    actual_retain = retain_source_scan
    captured = []

    def invalidate(root, selected):
        retained = actual_retain(root, selected)
        captured.append(retained)
        registry._profiles.clear()
        return retained

    monkeypatch.setattr(dispatch_module, "retain_source_scan", invalidate)
    result = process_pds2_scan(source, workspace_root=tmp_path, registry=registry)
    assert result.retained_source is captured[0]
    assert result.file_error is not None
    assert captured[0].retained_source_path.exists()


def test_invalid_workspace_after_retention_preserves_exact_source(tmp_path: Path) -> None:
    retained = _retained(tmp_path)
    missing_workspace = tmp_path / "missing-workspace"
    result = dispatch_retained_scan(
        missing_workspace,
        retained,
        registry=ModuleRegistry((get_module_profile(),)),
    )
    assert result.retained_source is retained
    assert result.file_error is not None
    assert retained.retained_source_path.exists()


def test_reordered_core_outcomes_are_application_failures_in_page_order(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    first_locator = _locator("other", "8")
    second_locator = _locator("other", "9")
    pages = (_page(retained, first_locator, 1), _page(retained, second_locator, 2))
    foreign = _profile("other", object())
    registry = ModuleRegistry((get_module_profile(), foreign))
    first_resolution = _registration(tmp_path, first_locator)
    second_resolution = _registration(tmp_path, second_locator)
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: pages)

    def reordered(_root, _registry, requests):
        first, second = tuple(requests)
        return (
            RouteDispatchSuccess(second, foreign, second_resolution, object()),
            RouteDispatchSuccess(first, foreign, first_resolution, object()),
        )

    monkeypatch.setattr(dispatch_module, "dispatch_routes", reordered)
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert tuple(page.source_page_number for page in result.pages) == (1, 2)
    assert all(
        page.failure_stage == "core_outcome_validation" for page in result.pages
    )
    assert result.application_failure_count == 2
    assert result.terminal_page_count == 2
    assert result.batch_status == "integration_failure"


@pytest.mark.parametrize("mismatch", ["request", "profile", "resolution"])
def test_core_success_alignment_mismatches_are_rejected(
    tmp_path: Path, monkeypatch, mismatch: str
) -> None:
    retained = _retained(tmp_path)
    locator = _locator("other", "a")
    other_locator = _locator("other", "b")
    page = _page(retained, locator, 1)
    foreign = _profile("other", object())
    wrong_profile = _profile("wrong", object())
    registry = ModuleRegistry((get_module_profile(), foreign, wrong_profile))
    resolution = _registration(tmp_path, locator)
    wrong_resolution = _registration(tmp_path, other_locator)
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: (page,))

    def dispatch(_root, _registry, requests):
        request = tuple(requests)[0]
        selected_request = (
            RouteDispatchRequest(other_locator, retained, 1)
            if mismatch == "request"
            else request
        )
        selected_profile = wrong_profile if mismatch == "profile" else foreign
        selected_resolution = (
            wrong_resolution if mismatch == "resolution" else resolution
        )
        return (
            RouteDispatchSuccess(
                selected_request,
                selected_profile,
                selected_resolution,
                object(),
            ),
        )

    monkeypatch.setattr(dispatch_module, "dispatch_routes", dispatch)
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert result.pages[0].failure_stage == "core_outcome_validation"
    assert isinstance(result.pages[0].error, ScoreFormDispatchIntegrationError)
    assert result.application_failure_count == 1
    assert result.dispatch_success_count == 0


def test_failure_outcome_with_wrong_request_is_marked_without_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    locator = _locator("other", "c")
    page = _page(retained, locator, 1)
    foreign = _profile("other", object())
    registry = ModuleRegistry((get_module_profile(), foreign))
    wrong_request = RouteDispatchRequest(_locator("other", "d"), retained, 1)
    original = RouteDispatchFailure(wrong_request, ValueError("core failure"))
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: (page,))
    monkeypatch.setattr(
        dispatch_module, "dispatch_routes", lambda *_args: (original,)
    )
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert result.pages[0].dispatch_outcome is original
    assert result.pages[0].failure_stage == "core_outcome_validation"
    assert result.dispatch_failure_count == 1
    assert result.terminal_page_count == 1


def test_duplicated_core_outcome_request_does_not_replace_later_page(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    first_locator = _locator("other", "d")
    second_locator = _locator("other", "e")
    pages = (_page(retained, first_locator, 1), _page(retained, second_locator, 2))
    foreign = _profile("other", object())
    registry = ModuleRegistry((get_module_profile(), foreign))
    first_resolution = _registration(tmp_path, first_locator)
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: pages)

    def duplicated(_root, _registry, requests):
        first_request, _second_request = tuple(requests)
        first = RouteDispatchSuccess(
            first_request, foreign, first_resolution, object()
        )
        return first, first

    monkeypatch.setattr(dispatch_module, "dispatch_routes", duplicated)
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert result.pages[0].failure_stage is None
    assert result.pages[1].failure_stage == "core_outcome_validation"
    assert result.pages[1].locator == second_locator
    assert result.dispatch_success_count == 1
    assert result.application_failure_count == 1
    assert result.terminal_page_count == 2


def test_wrong_scoreform_result_and_foreign_success_are_fully_accounted(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    score_locator = _locator("scoreform", "e")
    foreign_locator = _locator("other", "f")
    pages = (_page(retained, score_locator, 1), _page(retained, foreign_locator, 2))
    score_profile = _profile("scoreform", object())
    foreign_result = object()
    foreign = _profile("other", foreign_result)
    registry = ModuleRegistry((score_profile, foreign))
    score_resolution = _registration(tmp_path, score_locator)
    foreign_resolution = _registration(tmp_path, foreign_locator)
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: pages)

    def outcomes(_root, _registry, requests):
        score_request, foreign_request = tuple(requests)
        return (
            RouteDispatchSuccess(score_request, score_profile, score_resolution, object()),
            RouteDispatchSuccess(
                foreign_request, foreign, foreign_resolution, foreign_result
            ),
        )

    monkeypatch.setattr(dispatch_module, "dispatch_routes", outcomes)
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert result.application_failure_count == 1
    assert result.dispatch_success_count == 1
    assert result.other_module_success_count == 1
    assert result.terminal_page_count == result.total_source_pages == 2
    assert result.batch_status == "partial_success"
    assert result.exit_code() == 1
    assert "Application integration failures: 1" in format_pds2_dispatch_summary(result)


def test_wrong_scoreform_result_plus_valid_scoreform_page_is_partial(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    first_locator = _locator("scoreform", "f")
    second_locator = _locator("scoreform", "0")
    pages = (_page(retained, first_locator, 1), _page(retained, second_locator, 2))
    profile = ModuleProfile(
        "scoreform",
        "ScoreForm",
        frozenset({"1"}),
        frozenset({"PDS2"}),
        frozenset({"1"}),
        frozenset({"active"}),
        _scoreform_result,
    )
    registry = ModuleRegistry((profile,))
    first_resolution = _registration(tmp_path, first_locator)
    second_resolution = _registration(tmp_path, second_locator)
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: pages)

    def outcomes(_root, _registry, requests):
        first, second = tuple(requests)
        return (
            RouteDispatchSuccess(first, profile, first_resolution, object()),
            RouteDispatchSuccess(
                second,
                profile,
                second_resolution,
                _scoreform_result(second_resolution, retained, 2),
            ),
        )

    monkeypatch.setattr(dispatch_module, "dispatch_routes", outcomes)
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert result.application_failure_count == 1
    assert result.scoreform_page_score_count == 1
    assert result.dispatch_success_count == 1
    assert result.terminal_page_count == 2
    assert result.batch_status == "partial_success"
    assert result.exit_code() == 1


@pytest.mark.parametrize("score_first", (True, False))
def test_real_core_mixed_module_dispatch_preserves_opaque_result(
    tmp_path: Path, monkeypatch, score_first: bool
) -> None:
    retained = _retained(tmp_path)
    score_locator = _locator("scoreform", "1")
    foreign_locator = _locator("other", "2")
    ordered_locators = (
        (score_locator, foreign_locator)
        if score_first
        else (foreign_locator, score_locator)
    )
    pages = tuple(
        _page(retained, locator, number)
        for number, locator in enumerate(ordered_locators, start=1)
    )
    score_profile = ModuleProfile(
        "scoreform",
        "ScoreForm",
        frozenset({"1"}),
        frozenset({"PDS2"}),
        frozenset({"1"}),
        frozenset({"active"}),
        _scoreform_result,
    )
    opaque = object()
    foreign = _profile("other", opaque)
    registry = ModuleRegistry((score_profile, foreign))
    _registration(tmp_path, score_locator)
    _registration(tmp_path, foreign_locator)
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: pages)
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert result.complete_success
    assert result.successful_pages_by_module == (("other", 1), ("scoreform", 1))
    foreign_page = next(page for page in result.pages if page.locator == foreign_locator)
    foreign_outcome = foreign_page.dispatch_outcome
    assert isinstance(foreign_outcome, RouteDispatchSuccess)
    assert foreign_outcome.module_result is opaque
    assert result.scoreform_page_score_count == 1
    assert result.terminal_page_count == 2


def test_page_and_batch_model_invariants_reject_inconsistent_state(tmp_path: Path) -> None:
    retained = _retained(tmp_path)
    locator = _locator("other", "3")
    request = RouteDispatchRequest(locator, retained, 1)
    with pytest.raises(ValueError, match="raw payload"):
        Pds2ScanPageOutcome(1, locator=locator)
    with pytest.raises(ValueError, match="source page"):
        Pds2ScanPageOutcome(
            1,
            raw_payload_text="payload",
            locator=locator,
            dispatch_request=RouteDispatchRequest(locator, retained, 2),
        )
    with pytest.raises(ValueError, match="duplicates"):
        Pds2ScanPageOutcome(1, diagnostic_paths=("same.png", "same.png"))
    clean = Pds2ScanPageOutcome(
        1,
        raw_payload_text="payload",
        locator=locator,
        dispatch_request=request,
        failure_stage="request_construction",
        error=ValueError("failed"),
    )
    with pytest.raises(ValueError, match="unique and ascending"):
        Pds2ScanDispatchResult(retained, (clean, clean))


def test_ordered_partial_batch_isolates_missing_malformed_unknown_and_later_success(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained_pdf(tmp_path)
    score_two = _locator("scoreform", "4")
    unknown = _locator("missing", "5")
    score_five = _locator("scoreform", "6")
    pages = (
        Pds2ScanPageOutcome(
            1,
            failure_stage="qr_detection",
            error=ValueError("missing QR"),
        ),
        _page(retained, score_two, 2),
        Pds2ScanPageOutcome(
            3,
            raw_payload_text="PDS2|broken",
            failure_stage="payload_parsing",
            error=ValueError("malformed PDS2"),
        ),
        _page(retained, unknown, 4),
        _page(retained, score_five, 5),
    )
    score_profile = ModuleProfile(
        "scoreform",
        "ScoreForm",
        frozenset({"1"}),
        frozenset({"PDS2"}),
        frozenset({"1"}),
        frozenset({"active"}),
        _scoreform_result,
    )
    registry = ModuleRegistry((score_profile,))
    _registration(tmp_path, score_two)
    _registration(tmp_path, score_five)
    monkeypatch.setattr(dispatch_module, "_decode_pages", lambda *_args: pages)
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    assert tuple(page.source_page_number for page in result.pages) == (1, 2, 3, 4, 5)
    assert isinstance(result.pages[1].dispatch_outcome, RouteDispatchSuccess)
    assert isinstance(result.pages[3].dispatch_outcome, RouteDispatchFailure)
    assert isinstance(result.pages[4].dispatch_outcome, RouteDispatchSuccess)
    assert result.dispatch_success_count == 2
    assert result.dispatch_failure_count == 1
    assert result.pre_dispatch_failure_count == 2
    assert result.application_failure_count == 0
    assert result.terminal_page_count == 5
    assert result.batch_status == "partial_success"
    assert result.exit_code() == 1
    for page_number in (2, 4, 5):
        request = result.pages[page_number - 1].dispatch_request
        assert request is not None
        assert request.retained_source is retained
        assert request.source_page_number == page_number


def test_processing_uses_retained_bytes_after_external_original_is_deleted(
    tmp_path: Path, monkeypatch
) -> None:
    payload = f"PDS2|m=missing|c=class1|w=quiz1|r=rt_{'7' * 32}"
    source = _qr(tmp_path / "external.png", payload)
    registry = ModuleRegistry((get_module_profile(),))
    actual_retain = retain_source_scan
    retained_calls = []

    def retain_then_delete(root, selected):
        retained = actual_retain(root, selected)
        retained_calls.append(retained)
        Path(selected).unlink()
        return retained

    monkeypatch.setattr(dispatch_module, "retain_source_scan", retain_then_delete)
    result = process_pds2_scan(source, workspace_root=tmp_path, registry=registry)
    assert len(retained_calls) == 1
    assert result.retained_source is retained_calls[0]
    assert result.pages[0].raw_payload_text == payload
    assert result.retained_source.retained_source_path.exists()


def test_repeated_intake_creates_distinct_provenance(tmp_path: Path) -> None:
    payload = f"PDS2|m=missing|c=class1|w=quiz1|r=rt_{'8' * 32}"
    source = _qr(tmp_path / "external.png", payload)
    registry = ModuleRegistry((get_module_profile(),))
    first = process_pds2_scan(source, workspace_root=tmp_path, registry=registry)
    second = process_pds2_scan(source, workspace_root=tmp_path, registry=registry)
    assert first.retained_source is not None and second.retained_source is not None
    assert first.retained_source.source_scan_id != second.retained_source.source_scan_id
    assert first.retained_source.retained_source_path != second.retained_source.retained_source_path


def test_pdf_pages_count_once_load_one_at_a_time_and_isolate_conversion_failure(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained_pdf(tmp_path)
    count_calls = []
    load_calls = []

    def count(*_args, **_kwargs):
        count_calls.append(True)
        return 3

    def load(_retained_source, number, **_kwargs):
        load_calls.append(number)
        if number == 2:
            raise ScoreFormRetainedPageError("conversion failed")
        return np.full((30, 30, 3), 255, np.uint8)

    def detect(_image, *, source_page_number, **_kwargs):
        return QrPayloadDetectionResult(
            f"PDS2|m=missing|c=class1|w=quiz1|r=rt_{str(source_page_number) * 32}",
            "raw",
        )

    monkeypatch.setattr(dispatch_module, "retained_source_page_count", count)
    monkeypatch.setattr(dispatch_module, "load_retained_page_for_qr", load)
    monkeypatch.setattr(dispatch_module, "detect_qr_payload_text", detect)
    pages = dispatch_module._decode_pages(tmp_path, retained)
    assert count_calls == [True]
    assert load_calls == [1, 2, 3]
    assert tuple(page.source_page_number for page in pages) == (1, 2, 3)
    assert pages[1].failure_stage == "source_page_loading"
    assert pages[2].dispatch_request is not None


def test_missing_qr_preserves_diagnostic_directory_failure(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    diagnostic_error = OSError("diagnostic directory unavailable")
    monkeypatch.setattr(dispatch_module, "_qr_candidate_images", lambda _image: ())
    monkeypatch.setattr(
        dispatch_module,
        "save_qr_failure_diagnostics_with_status",
        lambda *_args, **_kwargs: QrDiagnosticWriteResult(
            errors=(diagnostic_error,)
        ),
    )
    detection = dispatch_module.detect_qr_payload_text(
        np.full((30, 30, 3), 255, np.uint8),
        retained_source=retained,
        source_page_number=1,
        workspace_root=tmp_path,
    )
    assert detection.raw_payload_text is None
    assert detection.error is not None
    assert detection.diagnostic_errors == (diagnostic_error,)
    assert detection.diagnostic_paths == ()


def test_qr_detection_continues_after_one_candidate_raises(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    candidates = (
        ("raw", np.full((30, 30, 3), 255, np.uint8)),
        ("scaled", np.full((60, 60, 3), 255, np.uint8)),
    )
    payload = f"PDS2|m=scoreform|c=class1|w=quiz1|r=rt_{'9' * 32}"
    calls = []

    class Detector:
        def detectAndDecode(self, _candidate):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("OpenCV candidate failure")
            return payload, None, None

    monkeypatch.setattr(dispatch_module, "_qr_candidate_images", lambda _image: candidates)
    monkeypatch.setattr(dispatch_module.cv2, "QRCodeDetector", Detector)

    detection = dispatch_module.detect_qr_payload_text(
        candidates[0][1],
        retained_source=retained,
        source_page_number=1,
        workspace_root=tmp_path,
    )

    assert detection.raw_payload_text == payload
    assert detection.decode_method == "scaled"
    assert detection.error is None
    assert calls == [True, True]


def test_qr_detection_reports_unreadable_when_every_candidate_raises(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    candidates = (("raw", np.full((30, 30, 3), 255, np.uint8)),)

    class Detector:
        def detectAndDecode(self, _candidate):
            raise RuntimeError("OpenCV candidate failure")

    monkeypatch.setattr(dispatch_module, "_qr_candidate_images", lambda _image: candidates)
    monkeypatch.setattr(dispatch_module.cv2, "QRCodeDetector", Detector)

    detection = dispatch_module.detect_qr_payload_text(
        candidates[0][1],
        retained_source=retained,
        source_page_number=1,
        workspace_root=tmp_path,
    )

    assert detection.raw_payload_text is None
    assert detection.decode_method is None
    assert isinstance(detection.error, ScoreFormQrUnreadableError)
    assert isinstance(detection.error.__cause__, RuntimeError)


def test_missing_qr_preserves_successful_and_failed_diagnostics_in_summary(
    tmp_path: Path, monkeypatch
) -> None:
    retained = _retained(tmp_path)
    diagnostic_error = OSError("one write failed")
    saved = str(tmp_path / "saved.png")
    monkeypatch.setattr(dispatch_module, "_qr_candidate_images", lambda _image: ())
    monkeypatch.setattr(
        dispatch_module,
        "save_qr_failure_diagnostics_with_status",
        lambda *_args, **_kwargs: QrDiagnosticWriteResult(
            paths=(saved,), errors=(diagnostic_error,)
        ),
    )
    monkeypatch.setattr(dispatch_module, "retained_source_page_count", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        dispatch_module,
        "load_retained_page_for_qr",
        lambda *_args, **_kwargs: np.full((30, 30, 3), 255, np.uint8),
    )
    registry = ModuleRegistry((get_module_profile(),))
    result = dispatch_retained_scan(tmp_path, retained, registry=registry)
    page = result.pages[0]
    assert page.failure_stage == "qr_detection"
    assert page.diagnostic_paths == (saved,)
    assert page.diagnostic_errors == (diagnostic_error,)
    summary = format_pds2_dispatch_summary(result)
    assert "Diagnostic write warnings:" in summary
    assert "one write failed" in summary


def test_diagnostic_helper_structures_directory_and_write_failures(
    tmp_path: Path, monkeypatch
) -> None:
    image = np.full((100, 100, 3), 255, np.uint8)
    monkeypatch.setattr(
        scoring,
        "_dated_local_output_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no directory")),
    )
    directory_result = scoring.save_qr_failure_diagnostics_with_status(
        image, "scan", 1, workspace_root=tmp_path
    )
    assert directory_result.paths == ()
    assert len(directory_result.errors) == 1

    monkeypatch.setattr(
        scoring,
        "_dated_local_output_dir",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    calls = []

    def mixed(path, _image):
        calls.append(path)
        if len(calls) == 1:
            return path, None
        return None, OSError("write failed")

    monkeypatch.setattr(scoring, "_write_diagnostic_image_with_status", mixed)
    mixed_result = scoring.save_qr_failure_diagnostics_with_status(
        image, "scan", 1, workspace_root=tmp_path
    )
    assert len(mixed_result.paths) == 1
    assert mixed_result.errors

    monkeypatch.setattr(
        scoring,
        "_write_diagnostic_image_with_status",
        lambda *_args: (None, OSError("all writes failed")),
    )
    failed_result = scoring.save_qr_failure_diagnostics_with_status(
        image, "scan", 1, workspace_root=tmp_path
    )
    assert failed_result.paths == ()
    assert len(failed_result.errors) >= 1
