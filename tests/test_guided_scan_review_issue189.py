from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scoreform import menu_scan_review


def _discovery(items, *, warning_count: int = 0):
    return SimpleNamespace(
        items=tuple(items),
        warning_count=warning_count,
        invalid_failure_count=warning_count,
        invalid_resolution_count=0,
        unsupported_v1_failure_count=0,
        unsupported_v1_resolution_count=0,
        orphan_resolution_count=0,
        provenance_mismatch_count=0,
        malformed_scoreform_details_count=0,
        foreign_record_count=0,
    )


def _item(filename: str):
    return SimpleNamespace(
        status="unresolved",
        failure_category="qr_decode",
        source_filename=filename,
        source_page_number=1,
    )


def test_global_review_entry_preserves_historical_unfiltered_discovery_call(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    def discover(root):
        calls.append((root, {}))
        return _discovery((_item("global.pdf"),))

    monkeypatch.setattr(
        menu_scan_review.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(menu_scan_review, "discover_scan_review_items", discover)
    monkeypatch.setattr(menu_scan_review, "clear_screen", lambda: None)
    monkeypatch.setattr("builtins.input", lambda *_args: "b")

    assert menu_scan_review.launch_scan_review_menu() == 0
    assert calls == [(tmp_path, {})]


def test_guided_review_filters_by_exact_retained_source_scan_id(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    calls = []
    source_scan_id = "scan_synthetic_189"

    def discover(root, **kwargs):
        calls.append((root, kwargs))
        assert kwargs == {"source_scan_id": source_scan_id}
        return _discovery((_item("this_scan.pdf"),), warning_count=7)

    monkeypatch.setattr(
        menu_scan_review.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(menu_scan_review, "discover_scan_review_items", discover)
    monkeypatch.setattr(menu_scan_review, "clear_screen", lambda: None)
    monkeypatch.setattr("builtins.input", lambda *_args: "b")

    assert (
        menu_scan_review.launch_scan_review_menu(
            source_scan_id=source_scan_id,
        )
        == 0
    )

    assert calls == [(tmp_path, {"source_scan_id": source_scan_id})]
    output = capsys.readouterr().out
    assert "Review This Scan" in output
    assert "this retained scan only" in output
    assert "this_scan.pdf" in output
    assert "Warning: 7 review record(s) ignored." not in output


def test_source_scoped_empty_state_is_truthful_and_bounded(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    source_scan_id = "scan_synthetic_189"
    monkeypatch.setattr(
        menu_scan_review.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        menu_scan_review,
        "discover_scan_review_items",
        lambda root, **kwargs: _discovery(()),
    )
    monkeypatch.setattr(menu_scan_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_scan_review, "pause_for_user", lambda: None)

    assert (
        menu_scan_review.launch_scan_review_menu(
            source_scan_id=source_scan_id,
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "No unresolved or deferred ScoreForm review items remain" in output
    assert "for this retained scan" in output
