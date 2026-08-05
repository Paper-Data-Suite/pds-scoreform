from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import pytest

import scoreform.academic_result_manifest_generation as generation_module
from scoreform.academic_result_manifest_generation import (
    ScoreFormManifestGenerationConflictError,
    ScoreFormManifestGenerationIntegrityError,
    generate_academic_result_manifest,
    list_academic_result_manifest_revisions,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.work_paths import (
    academic_result_manifest_relative_path,
    academic_result_manifest_revision_path,
    scoreform_work_paths,
)


def _workspace(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "Quiz",
                "question_count": 1,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A"},
                "standards": {"1": []},
            }
        ),
        encoding="utf-8",
    )
    result = ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id="class1",
        assignment_id="quiz1",
        student_id="student1",
        last_name="Synthetic",
        first_name="Learner",
        period="1",
        page_display="manual",
        score=1,
        total_points=1,
        answers=(ScoredAnswer(1, "A", True),),
        source_file="plain_paper_manual_entry",
    )
    assert export_scoreform_result_models((result,), workspace_root=tmp_path).succeeded
    return paths


def test_initial_exact_replay_and_successor_are_immutable(tmp_path):
    paths = _workspace(tmp_path)
    times = iter(
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            datetime(2026, 1, 3, tzinfo=timezone.utc),
        )
    )
    first = generate_academic_result_manifest(tmp_path, "class1", "quiz1", clock=lambda: next(times))
    first_stat = first.path.stat()
    replay = generate_academic_result_manifest(tmp_path, "class1", "quiz1", clock=lambda: next(times))
    assert first.disposition.value == "create_initial"
    assert replay.disposition.value == "reuse_existing"
    assert replay.content == first.content
    assert replay.manifest.generated_at == first.manifest.generated_at
    assert replay.path.stat().st_mtime_ns == first_stat.st_mtime_ns
    assignment = json.loads(paths.assignment_path.read_text(encoding="utf-8"))
    assignment["title"] = "Renamed Quiz"
    paths.assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    successor = generate_academic_result_manifest(tmp_path, "class1", "quiz1", clock=lambda: next(times))
    assert successor.disposition.value == "create_successor"
    assert successor.revision == 2
    assert first.path.read_bytes() == first.content
    assert successor.sha256 == hashlib.sha256(successor.path.read_bytes()).hexdigest()
    assert not (successor.path.parent / "latest.json").exists()
    assert not (successor.path.parent / "current.json").exists()


def test_paths_are_revision_addressed_and_core_valid(tmp_path):
    paths = _workspace(tmp_path)
    assert academic_result_manifest_relative_path(paths.work_ref, 17).endswith(
        "/exports/manifests/academic_results/17.json"
    )
    assert academic_result_manifest_revision_path(tmp_path, paths.work_ref, 17) == (
        paths.academic_result_manifests_dir / "17.json"
    )
    for revision in (True, 0, -1):
        with pytest.raises(ValueError):
            academic_result_manifest_relative_path(paths.work_ref, revision)


def test_history_rejects_noncanonical_names_and_bytes(tmp_path):
    paths = _workspace(tmp_path)
    result = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    malformed = result.path.parent / "01.json"
    malformed.write_bytes(result.content)
    with pytest.raises(ScoreFormManifestGenerationIntegrityError):
        list_academic_result_manifest_revisions(tmp_path, paths.work_ref)
    malformed.unlink()
    result.path.write_bytes(result.content + b" ")
    with pytest.raises(ScoreFormManifestGenerationIntegrityError):
        list_academic_result_manifest_revisions(tmp_path, paths.work_ref)


def test_existing_lock_rejects_concurrent_generation(tmp_path):
    paths = _workspace(tmp_path)
    paths.academic_result_manifests_dir.mkdir(parents=True)
    lock = paths.academic_result_manifests_dir / ".write.lock"
    lock.write_text("held", encoding="utf-8")
    with pytest.raises(ScoreFormManifestGenerationConflictError):
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert lock.read_text(encoding="utf-8") == "held"


def _replace_same_length(path, old: bytes, new: bytes, *, restore_mtime=True):
    original = path.read_bytes()
    replacement = original.replace(old, new)
    assert replacement != original
    assert len(replacement) == len(original)
    before = path.stat()
    path.write_bytes(replacement)
    if restore_mtime:
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    return original, replacement, before


def _assert_failed_initial_allocation(paths, changed_path, changed_bytes):
    assert changed_path.read_bytes() == changed_bytes
    assert not (paths.academic_result_manifests_dir / "1.json").exists()
    assert list_academic_result_manifest_revisions(
        paths.work_root.parents[5], paths.work_ref
    ) == ()
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_assignment_same_length_race_fails_exact_byte_gate_before_allocation(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)
    original_stat = paths.assignment_path.stat()
    changed: bytes | None = None

    def mutate_after_planning(_context):
        nonlocal changed
        _original, changed, _before = _replace_same_length(
            paths.assignment_path, b'"title": "Quiz"', b'"title": "Exam"'
        )

    monkeypatch.setattr(
        generation_module, "_run_prewrite_verification_hook", mutate_after_planning
    )
    with pytest.raises(
        ScoreFormManifestGenerationConflictError, match="assignment.json changed"
    ):
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert changed is not None
    assert paths.assignment_path.stat().st_size == original_stat.st_size
    assert paths.assignment_path.stat().st_mtime_ns == original_stat.st_mtime_ns
    _assert_failed_initial_allocation(paths, paths.assignment_path, changed)


def test_results_same_length_race_fails_exact_byte_gate_before_allocation(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)
    changed: bytes | None = None

    def mutate_after_planning(_context):
        nonlocal changed
        _original, changed, _before = _replace_same_length(
            paths.results_path, b"student1", b"student9"
        )

    monkeypatch.setattr(
        generation_module, "_run_prewrite_verification_hook", mutate_after_planning
    )
    with pytest.raises(
        ScoreFormManifestGenerationConflictError, match="results.csv changed"
    ):
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert changed is not None
    _assert_failed_initial_allocation(paths, paths.results_path, changed)


def test_exact_source_restoration_before_final_verification_may_create(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)
    assignment_bytes = paths.assignment_path.read_bytes()
    results_bytes = paths.results_path.read_bytes()

    def mutate_then_restore(_context):
        _replace_same_length(
            paths.assignment_path,
            b'"title": "Quiz"',
            b'"title": "Exam"',
            restore_mtime=False,
        )
        paths.assignment_path.write_bytes(assignment_bytes)

    monkeypatch.setattr(
        generation_module, "_run_prewrite_verification_hook", mutate_then_restore
    )
    result = generate_academic_result_manifest(
        tmp_path,
        "class1",
        "quiz1",
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.disposition.value == "create_initial"
    assert result.manifest.source_snapshot.assignment.sha256 == hashlib.sha256(
        assignment_bytes
    ).hexdigest()
    assert result.manifest.source_snapshot.results_history.sha256 == hashlib.sha256(
        results_bytes
    ).hexdigest()
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    assert paths.assignment_path.read_bytes() == assignment_bytes
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_replay_race_cannot_return_stale_reuse_existing(tmp_path, monkeypatch):
    paths = _workspace(tmp_path)
    first = generate_academic_result_manifest(
        tmp_path,
        "class1",
        "quiz1",
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    first_bytes = first.path.read_bytes()
    first_mtime = first.path.stat().st_mtime_ns
    changed: bytes | None = None

    def mutate_after_replay_planning(_context):
        nonlocal changed
        _original, changed, _before = _replace_same_length(
            paths.assignment_path, b'"title": "Quiz"', b'"title": "Exam"'
        )

    monkeypatch.setattr(
        generation_module,
        "_run_prewrite_verification_hook",
        mutate_after_replay_planning,
    )
    with pytest.raises(
        ScoreFormManifestGenerationConflictError, match="assignment.json changed"
    ):
        generate_academic_result_manifest(
            tmp_path,
            "class1",
            "quiz1",
            clock=lambda: (_ for _ in ()).throw(
                AssertionError("Replay must not request a new timestamp.")
            ),
        )
    assert changed is not None and paths.assignment_path.read_bytes() == changed
    assert first.path.read_bytes() == first_bytes
    assert first.path.stat().st_mtime_ns == first_mtime
    assert not (paths.academic_result_manifests_dir / "2.json").exists()
    assert tuple(
        item.revision
        for item in list_academic_result_manifest_revisions(tmp_path, paths.work_ref)
    ) == (1,)
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()
