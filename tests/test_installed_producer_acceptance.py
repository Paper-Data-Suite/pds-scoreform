from __future__ import annotations

from pathlib import Path

import scripts.verify_installed_producer_acceptance as acceptance


def test_acceptance_stage_order_is_complete_and_stable() -> None:
    assert acceptance.STAGES == (
        "installed provenance",
        "synthetic native work",
        "academic-work registration",
        "manifest revision 1",
        "public reader revision 1",
        "initial publication",
        "publication replay",
        "catalog revision 1",
        "Core verification revision 1",
        "native successor",
        "manifest revision 2",
        "supersession",
        "catalog revision 2",
        "public reader revision 2",
        "withdrawal",
        "final catalog",
        "registry audit",
        "immutability",
    )


def test_synthetic_assignment_is_small_unaligned_and_obviously_synthetic() -> None:
    assignment = acceptance._synthetic_assignment()
    assert assignment["assignment_id"] == "acceptance_quiz"
    assert assignment["title"] == "Synthetic Producer Acceptance"
    assert assignment["question_count"] == 3
    assert assignment["standards"] == {"1": [], "2": [], "3": []}
    assert "standards_profile_id" not in assignment


def test_synthetic_manual_results_preserve_distinct_response_states() -> None:
    first = acceptance._synthetic_result(1)
    second = acceptance._synthetic_result(2)

    assert first.result_origin == second.result_origin == "plain_paper_manual"
    assert first.student_id == second.student_id == "synthetic_student"
    assert first.page_display == second.page_display == "manual"
    assert first.source_file == second.source_file == "plain_paper_manual_entry"
    assert [answer.selected_answer for answer in first.answers] == [
        "A",
        "BLANK",
        "C",
    ]
    assert [answer.selected_answer for answer in second.answers] == [
        "B",
        "B",
        "AMBIGUOUS",
    ]
    assert first.score == 2
    assert second.score == 1


def test_acceptance_failure_is_bounded_to_stage_and_safe_message() -> None:
    error = acceptance.AcceptanceFailure("registry audit", "audit did not pass.")
    assert str(error) == "registry audit: audit did not pass."
    assert error.stage == "registry audit"
    assert error.message == "audit did not pass."


def test_installed_origin_helper_requires_site_packages_under_prefix(tmp_path: Path) -> None:
    assert not acceptance._is_isolated_installed_origin(tmp_path / "scoreform.py")


def test_acceptance_source_does_not_write_core_canonical_or_sqlite_state() -> None:
    source = Path("scripts/verify_installed_producer_acceptance.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    for forbidden in (
        "write_publication_record",
        "write_publication_withdrawal",
        "write_academic_work_registration",
        "sqlite3",
        "latest_attempt",
        "highest_attempt",
        "official_attempt",
        "calculate_grade",
    ):
        assert forbidden not in lowered
    for forbidden_import in (
        "import meridian",
        "from meridian",
        "import pds_meridian",
        "from pds_meridian",
        "import vitrine",
        "from vitrine",
        "import quillan",
        "from quillan",
        "import concord",
        "from concord",
        "import portia",
        "from portia",
    ):
        assert forbidden_import not in lowered


def test_acceptance_uses_production_scoreform_and_core_surfaces() -> None:
    source = Path("scripts/verify_installed_producer_acceptance.py").read_text(
        encoding="utf-8"
    )
    for required in (
        "initialize_scoreform_work_layout",
        "write_assignment_json",
        "export_scoreform_result_models",
        "register_scoreform_academic_work",
        "generate_academic_result_manifest",
        "publish_scoreform_academic_results",
        "supersede_scoreform_academic_results",
        "withdraw_scoreform_academic_result_publication",
        "rebuild_academic_catalog",
        "query_publication_catalog",
        "verify_publication_manifest",
        "read_academic_result_manifest",
        "audit_academic_registry",
    ):
        assert required in source


def test_release_install_runs_full_acceptance_only_for_wheel() -> None:
    installer = Path("scripts/validate_release_install.ps1").read_text(
        encoding="utf-8"
    )
    assert "scripts\\verify_installed_producer_acceptance.py" in installer
    assert '[switch]$RunProducerAcceptance' in installer
    assert '-Label "wheel" `' in installer
    assert '-RunProducerAcceptance' in installer
    wheel_call, sdist_call = installer.split(
        'Test-InstalledArtifact `', maxsplit=2
    )[1:]
    assert "-RunProducerAcceptance" in wheel_call
    assert "-RunProducerAcceptance" not in sdist_call
    assert "wheel-producer-acceptance-workspace" not in installer
    assert '"$Label-producer-acceptance-workspace"' in installer
