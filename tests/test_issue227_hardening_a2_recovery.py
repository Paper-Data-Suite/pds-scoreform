"""Issue 227 Hardening A2: journal, interruption, conflict and recovery tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pds_core.class_metadata import (
    create_class_metadata,
    load_class_metadata_for_class,
    write_class_metadata_for_class,
)
from pds_core.classes import load_class_roster, write_class_roster
from pds_core.routes import class_metadata_path, class_roster_path

from scoreform import class_pair_commit as pair
from scoreform.class_pair_recovery import (
    ClassPairRecoveryError,
    inspect_class_pair_recovery,
    intent_path,
    recover_class_pair,
)

CLASS = "english12_p2"
YEAR = "2026-2027"


def _commit(root: Path, suffix: str = "1", overwrite: bool = False) -> dict[str, str]:
    return pair.commit_class_pair(
        workspace_root=root,
        class_id=CLASS,
        period="2",
        students=[{
            "student_id": "student_" + suffix,
            "first_name": "Alex",
            "last_name": "Rivera",
        }],
        school_year=YEAR,
        overwrite=overwrite,
    )


def test_successful_new_commit_removes_intent(tmp_path: Path) -> None:
    _commit(tmp_path)
    assert not intent_path(tmp_path, CLASS).exists()
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "none"


def test_successful_overwrite_removes_intent_and_preserves_metadata(tmp_path: Path) -> None:
    _commit(tmp_path)
    old = load_class_metadata_for_class(tmp_path, CLASS)
    _commit(tmp_path, "2", overwrite=True)
    assert not intent_path(tmp_path, CLASS).exists()
    assert load_class_roster(tmp_path, CLASS).students[0].student_id == "student_2"
    assert load_class_metadata_for_class(tmp_path, CLASS).created_at == old.created_at


def test_interrupt_after_metadata_only_restores_absent_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt("interrupted after metadata")

    monkeypatch.setattr(pair, "write_class_roster", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path)
    assert intent_path(tmp_path, CLASS).is_file()
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "restore_metadata"
    assert recover_class_pair(tmp_path, CLASS) == "restored"
    assert not class_metadata_path(tmp_path, CLASS).exists()
    assert not class_roster_path(tmp_path, CLASS).exists()
    assert recover_class_pair(tmp_path, CLASS) == "none"


def test_interrupt_after_metadata_only_restores_previous_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit(tmp_path)
    previous_roster = class_roster_path(tmp_path, CLASS).read_bytes()
    previous_metadata = class_metadata_path(tmp_path, CLASS).read_bytes()

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt("interrupted before roster write")

    monkeypatch.setattr(pair, "write_class_roster", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path, "2", overwrite=True)
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "restore_metadata"
    assert recover_class_pair(tmp_path, CLASS) == "restored"
    assert class_metadata_path(tmp_path, CLASS).read_bytes() == previous_metadata
    assert class_roster_path(tmp_path, CLASS).read_bytes() == previous_roster


def test_interrupt_after_both_files_committed_finalizes_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_writer = pair.write_class_roster

    def commit_then_interrupt(*args: object, **kwargs: object) -> None:
        real_writer(*args, **kwargs)
        raise KeyboardInterrupt("interrupted after roster commit")

    monkeypatch.setattr(pair, "write_class_roster", commit_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path)
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "completed"
    assert recover_class_pair(tmp_path, CLASS) == "finalized"
    assert load_class_roster(tmp_path, CLASS).students[0].student_id == "student_1"
    assert load_class_metadata_for_class(tmp_path, CLASS).class_id == CLASS
    assert not intent_path(tmp_path, CLASS).exists()


def test_unresolved_intent_blocks_subsequent_scoreform_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(pair, "write_class_roster", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path)
    baseline = class_metadata_path(tmp_path, CLASS).read_bytes()
    with pytest.raises(pair.ClassPairCommitError, match="journal") as caught:
        _commit(tmp_path, "2", overwrite=True)
    assert caught.value.partial
    assert class_metadata_path(tmp_path, CLASS).read_bytes() == baseline


def test_recovery_rejects_intervening_core_metadata_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(pair, "write_class_roster", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path)
    foreign = create_class_metadata(
        CLASS, YEAR, created_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
        module_details={"core_writer": "concurrent"},
    )
    write_class_metadata_for_class(tmp_path, foreign, overwrite=True)
    baseline = class_metadata_path(tmp_path, CLASS).read_bytes()
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "conflict"
    with pytest.raises(ClassPairRecoveryError, match="conflict"):
        recover_class_pair(tmp_path, CLASS)
    assert class_metadata_path(tmp_path, CLASS).read_bytes() == baseline
    assert intent_path(tmp_path, CLASS).exists()


def test_recovery_rejects_intervening_core_roster_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit(tmp_path)
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(pair, "write_class_roster", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path, "2", overwrite=True)
    from pds_core.rosters import create_roster

    other = create_roster(CLASS, [{
        "student_id": "external_student", "first_name": "Pat",
        "last_name": "Test", "period": "2",
    }])
    write_class_roster(tmp_path, other, overwrite=True)
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "conflict"
    with pytest.raises(ClassPairRecoveryError):
        recover_class_pair(tmp_path, CLASS)
    assert load_class_roster(tmp_path, CLASS).students[0].student_id == "external_student"
    assert intent_path(tmp_path, CLASS).exists()


def test_corrupt_journal_refuses_recovery_without_mutating_anything(tmp_path: Path) -> None:
    _commit(tmp_path)
    baseline = (
        class_roster_path(tmp_path, CLASS).read_bytes(),
        class_metadata_path(tmp_path, CLASS).read_bytes(),
    )
    intent_path(tmp_path, CLASS).write_text("{corrupt", encoding="utf-8")
    with pytest.raises(ClassPairRecoveryError, match="invalid"):
        inspect_class_pair_recovery(tmp_path, CLASS)
    with pytest.raises(ClassPairRecoveryError):
        recover_class_pair(tmp_path, CLASS)
    assert baseline == (
        class_roster_path(tmp_path, CLASS).read_bytes(),
        class_metadata_path(tmp_path, CLASS).read_bytes(),
    )


def test_reentry_during_active_transaction_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = pair.write_class_metadata_for_class
    denied = []

    def concurrent(*args: object, **kwargs: object) -> object:
        try:
            _commit(tmp_path, suffix="other", overwrite=True)
        except pair.ClassPairCommitError as error:
            denied.append((error.partial, "journal" in str(error)))
        else:
            pytest.fail("Second paired writer was not excluded")
        return original(*args, **kwargs)

    monkeypatch.setattr(pair, "write_class_metadata_for_class", concurrent)
    _commit(tmp_path)
    assert denied == [(True, True)]
    assert not intent_path(tmp_path, CLASS).exists()


def test_normal_roster_failure_removes_journal_after_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic failure")

    monkeypatch.setattr(pair, "write_class_roster", failed)
    with pytest.raises(pair.ClassPairCommitError, match="restored"):
        _commit(tmp_path)
    assert not intent_path(tmp_path, CLASS).exists()
    assert recover_class_pair(tmp_path, CLASS) == "none"


def test_invalid_unsafe_class_name_rejected_before_journal(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        pair.commit_class_pair(
            workspace_root=tmp_path, class_id="../escape", period="2",
            students=[{"student_id":"student_1", "first_name":"Alex", "last_name":"Rivera"}],
            school_year=YEAR,
        )
    assert not (tmp_path / "escape" / ".scoreform-class-pair.intent.json").exists()


def test_interruption_before_first_core_write_clears_unmodified_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(pair, "write_class_metadata_for_class", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path)
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "unchanged"
    assert recover_class_pair(tmp_path, CLASS) == "unchanged"
    assert not intent_path(tmp_path, CLASS).exists()


def test_postcommit_metadata_interrupt_restores_prior_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit(tmp_path)
    old = class_metadata_path(tmp_path, CLASS).read_bytes()
    writer = pair.write_class_metadata_for_class

    def write_then_interrupt(*args: object, **kwargs: object) -> None:
        writer(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(pair, "write_class_metadata_for_class", write_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path, "2", overwrite=True)
    assert inspect_class_pair_recovery(tmp_path, CLASS) == "restore_metadata"
    assert recover_class_pair(tmp_path, CLASS) == "restored"
    assert class_metadata_path(tmp_path, CLASS).read_bytes() == old


def test_invalid_encoded_backup_blocks_manual_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(pair, "write_class_roster", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _commit(tmp_path)
    path = intent_path(tmp_path, CLASS)
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["old_metadata_base64"] = "not_valid_base64!*"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ClassPairRecoveryError, match="invalid"):
        recover_class_pair(tmp_path, CLASS)
    assert path.exists()
