from __future__ import annotations

import ast
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


def test_combined_runner_authenticates_exact_core_065() -> None:
    assert CORE_VERSION == "0.6.5"
    assert (
        CORE_WHEEL_SHA256
        == "9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18"
    )


def test_v011_physical_document_keeps_human_adjudication_explicit() -> None:
    text = Path("docs/v0.11.0_combined_acceptance.md").read_text(encoding="utf-8")

    assert "project owner" in text.casefold()
    assert "automation must not claim" in text.casefold()
    assert "actual size/100%" in text
    assert "missing-page" in text.casefold()
    assert "Share Results with Meridian" in text
    assert "sanitized" in text.casefold()


def test_v011_combined_harness_remains_available_as_historical_evidence() -> None:
    assert Path("scripts/run_v011_combined_wheel_acceptance.py").is_file()
    assert Path("scripts/verify_installed_v011_combined_acceptance.py").is_file()
    assert Path("docs/v0.11.0_combined_acceptance.md").is_file()

def test_guided_acceptance_uses_core_navigation_token_for_optional_menu_exit() -> None:
    source = Path(
        "scripts/verify_installed_v011_combined_acceptance.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    guided_choices: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_run_guided_scan":
            continue
        if len(node.args) < 3 or not isinstance(node.args[2], ast.List):
            continue
        values = tuple(
            element.value
            for element in node.args[2].elts
            if isinstance(element, ast.Constant)
            and isinstance(element.value, str)
        )
        guided_choices.append(values)

    assert guided_choices.count(("1", "b", "b")) == 2
    assert guided_choices.count(("b",)) == 1
    assert ("1", "2") not in guided_choices
    assert ("2",) not in guided_choices
    assert ("1", "back") not in guided_choices
    assert ("back",) not in guided_choices

    assert "partial-first-page.pdf" in source
    assert "def _first_page_pdf(" in source
    assert "dpi=250" in source
    assert "partial-first-page.png" not in source



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
