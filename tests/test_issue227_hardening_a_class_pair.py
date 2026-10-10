"""Issue #227 Hardening A1: bounded two-file failure compensation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pds_core.class_metadata import (
    create_class_metadata,
    load_class_metadata_for_class,
    write_class_metadata_for_class,
)
from pds_core.classes import load_class_roster
from pds_core.routes import class_metadata_path, class_roster_path

from scoreform import class_pair_commit as pair
from scoreform.workflows import write_roster_with_class_metadata

CLASS = "english12_p2"
YEAR = "2026-2027"


def _student(suffix: str = "1") -> list[dict[str, str]]:
    return [
        {"student_id": "student_" + suffix, "first_name": "Alex", "last_name": "Rivera"}
    ]


def _commit(root, *, suffix="1", overwrite=False):
    return pair.commit_class_pair(
        workspace_root=root,
        class_id=CLASS,
        period="2",
        students=_student(suffix),
        school_year=YEAR,
        overwrite=overwrite,
    )


def test_new_class_commits_both_core_files(tmp_path):
    result = _commit(tmp_path)
    assert result == {
        "roster_path": str(class_roster_path(tmp_path, CLASS)),
        "metadata_path": str(class_metadata_path(tmp_path, CLASS)),
    }
    assert load_class_roster(tmp_path, CLASS).students[0].student_id == "student_1"
    metadata = load_class_metadata_for_class(tmp_path, CLASS)
    assert metadata.class_id == CLASS
    assert metadata.school_year == YEAR


def test_overwrite_preserves_created_at_and_module_details(tmp_path):
    _commit(tmp_path)
    old = create_class_metadata(
        CLASS,
        YEAR,
        created_at=datetime(2025, 7, 1, tzinfo=timezone.utc),
        module_details={"source": "synthetic_preserved"},
    )
    write_class_metadata_for_class(tmp_path, old, overwrite=True)
    _commit(tmp_path, suffix="2", overwrite=True)
    updated = load_class_metadata_for_class(tmp_path, CLASS)
    assert updated.created_at == old.created_at
    assert updated.module_details == old.module_details
    assert updated.updated_at >= old.updated_at
    assert load_class_roster(tmp_path, CLASS).students[0].student_id == "student_2"


def test_overwrite_false_rejects_existing_pair_before_any_mutation(tmp_path):
    _commit(tmp_path)
    roster = class_roster_path(tmp_path, CLASS)
    metadata = class_metadata_path(tmp_path, CLASS)
    baseline = roster.read_bytes(), metadata.read_bytes()
    with pytest.raises(pair.ClassPairCommitError, match="overwrite"):
        _commit(tmp_path, suffix="2", overwrite=False)
    assert (roster.read_bytes(), metadata.read_bytes()) == baseline


def test_invalid_school_year_does_not_modify_existing_files(tmp_path):
    _commit(tmp_path)
    roster = class_roster_path(tmp_path, CLASS)
    metadata = class_metadata_path(tmp_path, CLASS)
    baseline = roster.read_bytes(), metadata.read_bytes()
    with pytest.raises(ValueError):
        pair.commit_class_pair(
            workspace_root=tmp_path,
            class_id=CLASS,
            period="2",
            students=_student("2"),
            school_year="invalid_year",
            overwrite=True,
        )
    assert (roster.read_bytes(), metadata.read_bytes()) == baseline


def test_metadata_failure_preserves_prior_roster(tmp_path, monkeypatch):
    _commit(tmp_path)
    roster = class_roster_path(tmp_path, CLASS)
    metadata = class_metadata_path(tmp_path, CLASS)
    baseline = roster.read_bytes(), metadata.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("synthetic metadata failure")

    monkeypatch.setattr(pair, "write_class_metadata_for_class", fail)
    with pytest.raises(pair.ClassPairCommitError, match="roster unchanged") as caught:
        _commit(tmp_path, suffix="2", overwrite=True)
    assert not caught.value.partial
    assert (roster.read_bytes(), metadata.read_bytes()) == baseline


def test_roster_failure_compensates_existing_metadata_exactly(tmp_path, monkeypatch):
    _commit(tmp_path)
    roster = class_roster_path(tmp_path, CLASS)
    metadata = class_metadata_path(tmp_path, CLASS)
    baseline = roster.read_bytes(), metadata.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("synthetic roster failure")

    monkeypatch.setattr(pair, "write_class_roster", fail)
    with pytest.raises(pair.ClassPairCommitError, match="restored") as caught:
        _commit(tmp_path, suffix="2", overwrite=True)
    assert not caught.value.partial
    assert (roster.read_bytes(), metadata.read_bytes()) == baseline


def test_roster_failure_removes_new_metadata_without_fabricating_roster(
    tmp_path, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise OSError("synthetic roster failure")

    monkeypatch.setattr(pair, "write_class_roster", fail)
    with pytest.raises(pair.ClassPairCommitError, match="restored") as caught:
        _commit(tmp_path)
    assert not caught.value.partial
    assert not class_roster_path(tmp_path, CLASS).exists()
    assert not class_metadata_path(tmp_path, CLASS).exists()


def test_postcommit_roster_exception_reports_partial_and_never_erases_it(
    tmp_path, monkeypatch
):
    original = pair.write_class_roster

    def commit_then_raise(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("simulated failure after roster commit")

    monkeypatch.setattr(pair, "write_class_roster", commit_then_raise)
    with pytest.raises(pair.ClassPairCommitError, match="PARTIAL") as caught:
        _commit(tmp_path)
    assert caught.value.partial
    assert load_class_roster(tmp_path, CLASS).students[0].student_id == "student_1"
    # A postcommit failure must not roll metadata back to absence and leave a
    # committed roster orphaned. Preserve the pair and report uncertainty.
    assert load_class_metadata_for_class(tmp_path, CLASS).class_id == CLASS


def test_metadata_postcommit_error_reports_partial_without_writing_roster(
    tmp_path, monkeypatch
):
    original = pair.write_class_metadata_for_class

    def commit_then_raise(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("simulated failure after metadata commit")

    monkeypatch.setattr(pair, "write_class_metadata_for_class", commit_then_raise)
    with pytest.raises(pair.ClassPairCommitError, match="may have been committed") as caught:
        _commit(tmp_path)
    assert caught.value.partial
    assert not class_roster_path(tmp_path, CLASS).exists()
    assert load_class_metadata_for_class(tmp_path, CLASS).class_id == CLASS


def test_postcommit_roster_error_during_update_retains_new_pair(
    tmp_path, monkeypatch
):
    _commit(tmp_path)
    old_roster = class_roster_path(tmp_path, CLASS).read_bytes()
    old_metadata = class_metadata_path(tmp_path, CLASS).read_bytes()
    original = pair.write_class_roster

    def commit_then_raise(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("simulated failure after roster update")

    monkeypatch.setattr(pair, "write_class_roster", commit_then_raise)
    with pytest.raises(pair.ClassPairCommitError, match="PARTIAL") as caught:
        _commit(tmp_path, suffix="2", overwrite=True)
    assert caught.value.partial
    assert load_class_roster(tmp_path, CLASS).students[0].student_id == "student_2"
    assert load_class_metadata_for_class(tmp_path, CLASS).class_id == CLASS
    assert class_roster_path(tmp_path, CLASS).read_bytes() != old_roster
    assert class_metadata_path(tmp_path, CLASS).read_bytes() != old_metadata


def test_failed_metadata_recovery_is_reported_as_partial(
    tmp_path, monkeypatch
):
    _commit(tmp_path)
    roster = class_roster_path(tmp_path, CLASS)
    baseline = roster.read_bytes()

    def fail_roster(*_args, **_kwargs):
        raise OSError("simulated roster failure")

    def fail_recovery(*_args, **_kwargs):
        raise OSError("simulated recovery failure")

    monkeypatch.setattr(pair, "write_class_roster", fail_roster)
    monkeypatch.setattr(pair, "_restore_if_unchanged", fail_recovery)
    with pytest.raises(pair.ClassPairCommitError, match="PARTIAL") as caught:
        _commit(tmp_path, suffix="2", overwrite=True)
    assert caught.value.partial
    assert roster.read_bytes() == baseline


def test_metadata_intervening_change_is_never_overwritten_on_failure(
    tmp_path, monkeypatch
):
    _commit(tmp_path)
    roster = class_roster_path(tmp_path, CLASS)
    metadata_path = class_metadata_path(tmp_path, CLASS)
    before_roster = roster.read_bytes()
    divergent = create_class_metadata(
        CLASS,
        YEAR,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        module_details={"changed": "during_failure"},
    )

    def change_metadata_then_fail(*_args, **_kwargs):
        write_class_metadata_for_class(tmp_path, divergent, overwrite=True)
        raise OSError("roster failure")

    monkeypatch.setattr(pair, "write_class_roster", change_metadata_then_fail)
    with pytest.raises(pair.ClassPairCommitError, match="PARTIAL") as caught:
        _commit(tmp_path, suffix="2", overwrite=True)
    assert caught.value.partial
    assert roster.read_bytes() == before_roster
    assert metadata_path.read_bytes() != b""
    assert load_class_metadata_for_class(tmp_path, CLASS).module_details == {
        "changed": "during_failure"
    }


def test_preflight_rejects_canonical_symlink(tmp_path):
    class_dir = tmp_path / "classes" / CLASS
    class_dir.mkdir(parents=True)
    target = tmp_path / "target.csv"
    target.write_bytes(b"keep")
    link = class_roster_path(tmp_path, CLASS)
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(pair.ClassPairCommitError, match="symbolic link"):
        _commit(tmp_path)
    assert link.is_symlink()
    assert target.read_bytes() == b"keep"
    assert not class_metadata_path(tmp_path, CLASS).exists()


def test_legacy_ui_shape_and_partial_failure_reporting(tmp_path, monkeypatch, capsys):
    original = pair.write_class_roster

    def commit_then_raise(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("synthetic postcommit failure")

    monkeypatch.setattr(pair, "write_class_roster", commit_then_raise)
    outcome = write_roster_with_class_metadata(
        workspace_root=tmp_path,
        class_id=CLASS,
        period="2",
        students=_student(),
        school_year=YEAR,
    )
    assert outcome is None
    assert "PARTIAL CLASS UPDATE" in capsys.readouterr().out
