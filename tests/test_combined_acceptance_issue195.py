from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_v011_combined_wheel_acceptance import (
    CORE_VERSION,
    CORE_WHEEL_SHA256,
)
from scripts.verify_installed_v011_combined_acceptance import (
    AcceptanceFailure,
    _installed_environment,
    _pairwise_disjoint,
    _select_one,
)


def test_semantic_selection_does_not_depend_on_input_order() -> None:
    records = (
        {"kind": "packet", "id": "third"},
        {"kind": "individual", "id": "wanted"},
        {"kind": "packet", "id": "first"},
    )

    selected = _select_one(
        reversed(records),
        lambda record: record["kind"] == "individual",
        label="individual issuance",
    )

    assert selected["id"] == "wanted"


def test_semantic_selection_rejects_zero_or_multiple_matches() -> None:
    with pytest.raises(AcceptanceFailure, match="found 0"):
        _select_one((1, 2), lambda value: value == 3, label="record")

    with pytest.raises(AcceptanceFailure, match="found 2"):
        _select_one((1, 1, 2), lambda value: value == 1, label="record")


def test_cross_target_identity_helper_is_order_independent() -> None:
    _pairwise_disjoint(
        (
            ("target-b", {"b2", "b1"}),
            ("target-a", {"a2", "a1"}),
            ("target-c", {"c1"}),
        )
    )

    with pytest.raises(AcceptanceFailure, match="reused identity"):
        _pairwise_disjoint(
            (
                ("target-b", {"shared", "b1"}),
                ("target-a", {"a1", "shared"}),
            )
        )


def test_installed_environment_removes_python_path_contamination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "private-source-checkout")
    monkeypatch.setenv("PYTHONHOME", "private-python-home")

    environment = _installed_environment(tmp_path / "workspace")

    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PDS_WORKSPACE_ROOT"] == str(tmp_path / "workspace")


def test_combined_acceptance_does_not_delegate_to_focused_verifiers() -> None:
    source = Path(
        "scripts/verify_installed_v011_combined_acceptance.py"
    ).read_text(encoding="utf-8")

    assert "verify_installed_assignment_copy_acceptance.py" not in source
    assert "verify_installed_assignment_preset_acceptance.py" not in source
    assert "verify_installed_assignment_bulk_entry_acceptance.py" not in source
    assert "verify_installed_multi_class_generation_acceptance.py" not in source
    assert "verify_installed_guided_scan_to_results_acceptance.py" not in source
    assert "verify_installed_share_results_with_meridian_acceptance.py" not in source


def test_combined_runner_authenticates_exact_core_063() -> None:
    assert CORE_VERSION == "0.6.3"
    assert (
        CORE_WHEEL_SHA256
        == "98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5"
    )


def test_v011_physical_document_keeps_human_adjudication_explicit() -> None:
    text = Path("docs/v0.11.0_combined_acceptance.md").read_text(encoding="utf-8")

    assert "project owner" in text.casefold()
    assert "automation must not claim" in text.casefold()
    assert "actual size/100%" in text
    assert "missing-page" in text.casefold()
    assert "Share Results with Meridian" in text
    assert "sanitized" in text.casefold()


def test_ci_wires_combined_installed_acceptance_cross_platform() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = Path(".github/workflows/release-readiness.yml").read_text(
        encoding="utf-8"
    )

    assert "combined-v011-wheel-qualification" in ci
    assert "windows-latest" in ci
    assert "ubuntu-latest" in ci
    assert "run_v011_combined_wheel_acceptance.py" in ci
    assert "verify_installed_v011_combined_acceptance.py" in release

def test_guided_acceptance_uses_core_navigation_token_for_optional_menu_exit() -> None:
    source = Path(
        "scripts/verify_installed_v011_combined_acceptance.py"
    ).read_text(encoding="utf-8")

    assert '_run_guided_scan(source_pdf, session, ["1", "b"])' in source
    assert '_run_guided_scan(partial, failure_session, ["b"])' in source
    assert 'partial-first-page.pdf' in source
    assert 'def _first_page_pdf(' in source
    assert 'dpi=250' in source
    assert 'partial-first-page.png' not in source
    assert 'source_pdf, recovered_session, ["1", "b"]' in source
    assert '_run_guided_scan(source_pdf, session, ["1", "2"])' not in source
    assert '_run_guided_scan(partial, failure_session, ["2"])' not in source
    assert '["1", "back"]' not in source
    assert '["back"]' not in source



def test_combined_diagnostic_privacy_probe_uses_supported_contract_values() -> None:
    source = Path(
        "scripts/verify_installed_v011_combined_acceptance.py"
    ).read_text(encoding="utf-8")

    assert 'component="diagnostics"' in source
    assert 'workflow="retain_diagnostics"' in source
    assert 'stage="retention"' in source
    assert 'outcome="warning"' in source
    assert 'code="diagnostic_retention_warning"' in source
    assert 'component="combined_acceptance"' not in source
    assert 'workflow="physical_recovery"' not in source
    assert 'code="combined_privacy_probe"' not in source
