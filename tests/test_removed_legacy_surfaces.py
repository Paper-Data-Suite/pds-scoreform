import importlib
import inspect

import pytest

from scoreform import cli, results, scoring, workflows


def test_removed_qr_metadata_apis_are_not_exposed():
    for name in (
        "validate_qr_metadata",
        "validate_qr_identifier",
        "is_safe_qr_identifier",
        "decode_qr_from_image",
        "_decode_qr_from_image_with_status",
        "parse_qr_payload",
        "_score_page_qr_aware",
        "QRBatchSummary",
        "QRBatchResults",
        "process_file_qr_aware",
    ):
        assert not hasattr(scoring, name)


def test_removed_result_history_apis_and_origins_are_not_exposed():
    assert not hasattr(results, "_legacy_export_routed_results")
    assert results.RESULT_ORIGINS == {
        "pds2_scan",
        "plain_paper_manual",
        "scan_review_manual",
    }
    for name in ("_model_from_v1", "_migrate_v1_history", "_routed_headers"):
        assert not hasattr(results, name)
    source = inspect.getsource(results)
    assert 'result_origin="legacy_scan"' not in source
    assert "v1_width" not in source


def test_removed_workspace_discovery_fallback_is_not_exposed():
    assert not hasattr(workflows, "_discover_class_rosters_in_legacy_directory")


def test_migration_module_and_cli_boundary_are_absent():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("scoreform.migration")
    source = inspect.getsource(cli)
    assert "ScoreFormMigrationPendingError" not in source
    assert "print_migration_error" not in source
    assert "scoreform.migration" not in source
