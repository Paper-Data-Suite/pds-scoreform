from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scoreform.academic_result_manifest_generation as generation_module
from scoreform.academic_result_manifest_generation import (
    ScoreFormManifestGenerationConflictError,
    ScoreFormManifestGenerationError,
    ScoreFormManifestGenerationIntegrityError,
    ScoreFormManifestGenerationPartialSuccessError,
    ScoreFormManifestGenerationWriteError,
    generate_academic_result_manifest,
    list_academic_result_manifest_revisions,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    export_scoreform_result_models,
    routed_results_v2_headers,
)
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


def _set_assignment_question_count(paths, question_count):
    assignment = json.loads(paths.assignment_path.read_text(encoding="utf-8"))
    assignment["question_count"] = question_count
    assignment["answer_key"] = {
        str(number): "A" for number in range(1, question_count + 1)
    }
    assignment["standards"] = {
        str(number): [] for number in range(1, question_count + 1)
    }
    paths.assignment_path.write_text(json.dumps(assignment), encoding="utf-8")


def _set_header_only_results(paths, question_count):
    paths.results_path.write_bytes(
        (",".join(routed_results_v2_headers(question_count)) + "\r\n").encode()
    )


def _assert_width_integrity_failure(tmp_path, paths):
    assignment_bytes = paths.assignment_path.read_bytes()
    results_bytes = paths.results_path.read_bytes()
    with pytest.raises(
        ScoreFormManifestGenerationIntegrityError,
        match="question structure does not match assignment.json",
    ):
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert paths.assignment_path.read_bytes() == assignment_bytes
    assert paths.results_path.read_bytes() == results_bytes
    assert not (paths.academic_result_manifests_dir / "1.json").exists()
    assert list_academic_result_manifest_revisions(tmp_path, paths.work_ref) == ()
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_header_only_results_wider_than_assignment_fail_before_allocation(tmp_path):
    paths = _workspace(tmp_path)
    _set_header_only_results(paths, 2)
    _assert_width_integrity_failure(tmp_path, paths)


def test_header_only_results_narrower_than_assignment_fail_before_allocation(
    tmp_path,
):
    paths = _workspace(tmp_path)
    _set_assignment_question_count(paths, 2)
    _set_header_only_results(paths, 1)
    _assert_width_integrity_failure(tmp_path, paths)


def test_wider_results_header_with_blank_trailing_question_cells_fails_closed(
    tmp_path,
):
    paths = _workspace(tmp_path)
    with paths.results_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        row = next(reader)
    headers = routed_results_v2_headers(2)
    row["Q2"] = ""
    row["Q2_Correct"] = ""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerow(row)
    paths.results_path.write_bytes(output.getvalue().encode())

    _assert_width_integrity_failure(tmp_path, paths)


def test_matching_header_only_results_generate_empty_students(tmp_path):
    paths = _workspace(tmp_path)
    _set_header_only_results(paths, 1)
    result = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert result.manifest.students == ()
    assert result.path == paths.academic_result_manifests_dir / "1.json"
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


def _fail_selected_unlinks(monkeypatch, names):
    real_unlink = Path.unlink

    def fail_selected(path, *args, **kwargs):
        if path.name in names:
            raise PermissionError(f"injected unlink failure for {path.name}")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_selected)


def test_validation_failure_exposes_lock_cleanup_failure_without_allocation(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)
    paths.assignment_path.write_bytes(b"{")
    _fail_selected_unlinks(monkeypatch, {".write.lock"})

    with pytest.raises(ScoreFormManifestGenerationError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    error = caught.value
    assert isinstance(error, generation_module.ScoreFormManifestGenerationValidationError)
    assert error.lock_cleanup_failure is not None
    assert error.lock_cleanup_failure.error.__class__ is PermissionError
    assert error.lock_cleanup_failure.relative_path.endswith(
        "/exports/manifests/academic_results/.write.lock"
    )
    assert not (paths.academic_result_manifests_dir / "1.json").exists()
    assert (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_nondurable_write_and_both_cleanup_failures_remain_public(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)

    def fail_file_fsync(_descriptor):
        raise OSError("injected file fsync failure")

    monkeypatch.setattr(generation_module.os, "fsync", fail_file_fsync)
    _fail_selected_unlinks(monkeypatch, {"1.json", ".write.lock"})

    with pytest.raises(ScoreFormManifestGenerationWriteError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    error = caught.value
    assert not isinstance(error, ScoreFormManifestGenerationPartialSuccessError)
    assert error.incomplete_target_cleanup_failure is not None
    assert error.lock_cleanup_failure is not None
    assert "incomplete-file cleanup also failed" in str(error)
    assert (paths.academic_result_manifests_dir / "1.json").exists()
    assert (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_directory_sync_and_lock_cleanup_failure_report_durable_revision(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)

    def fail_directory_sync(_directory):
        raise OSError("injected directory sync failure")

    monkeypatch.setattr(generation_module, "_sync_directory", fail_directory_sync)
    _fail_selected_unlinks(monkeypatch, {".write.lock"})

    with pytest.raises(ScoreFormManifestGenerationPartialSuccessError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    error = caught.value
    assert error.state.operation == "directory_sync"
    assert error.state.revision == 1
    assert error.state.path == paths.academic_result_manifests_dir / "1.json"
    assert error.state.expected_sha256 == hashlib.sha256(
        error.state.path.read_bytes()
    ).hexdigest()
    assert error.state.durable_file_exists
    assert error.state.lock_cleanup_failure == error.lock_cleanup_failure
    assert (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_final_history_reload_failure_is_partial_and_removes_lock(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)
    real_load_history = generation_module._load_history
    calls = 0

    def fail_final_reload(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ScoreFormManifestGenerationIntegrityError(
                "injected final history reload failure"
            )
        return real_load_history(*args, **kwargs)

    monkeypatch.setattr(generation_module, "_load_history", fail_final_reload)
    with pytest.raises(ScoreFormManifestGenerationPartialSuccessError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    error = caught.value
    content = error.state.path.read_bytes()
    assert error.state.operation == "generate"
    assert error.state.revision == 1
    assert hashlib.sha256(content).hexdigest() == error.state.expected_sha256
    assert isinstance(error.__cause__, ScoreFormManifestGenerationIntegrityError)
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_successful_generation_with_lock_cleanup_failure_becomes_partial(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)
    _fail_selected_unlinks(monkeypatch, {".write.lock"})

    with pytest.raises(ScoreFormManifestGenerationPartialSuccessError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    error = caught.value
    assert error.state.operation == "lock_cleanup"
    assert error.state.revision == 1
    assert error.state.durable_file_exists
    assert error.state.path.read_bytes()
    assert error.state.lock_cleanup_failure == error.lock_cleanup_failure
    assert (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_replay_with_lock_cleanup_failure_never_returns_ordinary_success(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)
    first = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    first_bytes = first.path.read_bytes()
    first_mtime = first.path.stat().st_mtime_ns
    _fail_selected_unlinks(monkeypatch, {".write.lock"})

    with pytest.raises(ScoreFormManifestGenerationPartialSuccessError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    error = caught.value
    assert error.state.operation == "lock_cleanup"
    assert error.state.revision == 1
    assert error.lock_cleanup_failure is not None
    assert first.path.read_bytes() == first_bytes
    assert first.path.stat().st_mtime_ns == first_mtime
    assert not (paths.academic_result_manifests_dir / "2.json").exists()
    assert (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_exclusive_target_collision_preserves_foreign_target(tmp_path, monkeypatch):
    paths = _workspace(tmp_path)
    target = paths.academic_result_manifests_dir / "1.json"

    def inject_collision(_context):
        target.write_bytes(b"concurrent-owner-bytes")

    monkeypatch.setattr(
        generation_module, "_run_prewrite_verification_hook", inject_collision
    )
    with pytest.raises(ScoreFormManifestGenerationConflictError):
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    assert target.read_bytes() == b"concurrent-owner-bytes"
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_failure_before_target_creation_allocates_nothing(tmp_path, monkeypatch):
    paths = _workspace(tmp_path)

    def fail_before_create(_path, _content):
        raise ScoreFormManifestGenerationWriteError(
            "injected failure before target creation"
        )

    monkeypatch.setattr(generation_module, "_write_new_revision", fail_before_create)
    with pytest.raises(ScoreFormManifestGenerationWriteError):
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    assert not (paths.academic_result_manifests_dir / "1.json").exists()
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()


@pytest.mark.parametrize("stage", ("partial_write", "flush", "file_fsync"))
def test_nondurable_stream_failures_remove_only_the_incomplete_target(
    tmp_path, monkeypatch, stage
):
    paths = _workspace(tmp_path)
    assignment_bytes = paths.assignment_path.read_bytes()
    results_bytes = paths.results_path.read_bytes()
    real_fdopen = os.fdopen

    class InjectedFailureStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.stream.close()
            return False

        def write(self, content):
            if stage == "partial_write":
                return self.stream.write(content[: len(content) // 2])
            return self.stream.write(content)

        def flush(self):
            if stage == "flush":
                raise OSError("injected flush failure")
            return self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

    if stage in {"partial_write", "flush"}:
        monkeypatch.setattr(
            generation_module.os,
            "fdopen",
            lambda descriptor, mode, closefd: InjectedFailureStream(
                real_fdopen(descriptor, mode, closefd=closefd)
            ),
        )
    else:
        monkeypatch.setattr(
            generation_module.os,
            "fsync",
            lambda _descriptor: (_ for _ in ()).throw(
                OSError("injected file fsync failure")
            ),
        )

    with pytest.raises(ScoreFormManifestGenerationWriteError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    assert caught.value.incomplete_target_cleanup_failure is None
    assert not (paths.academic_result_manifests_dir / "1.json").exists()
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()
    assert paths.assignment_path.read_bytes() == assignment_bytes
    assert paths.results_path.read_bytes() == results_bytes


def test_result_model_construction_failure_after_durability_is_partial(
    tmp_path, monkeypatch
):
    paths = _workspace(tmp_path)

    def fail_result_model(**_kwargs):
        raise RuntimeError("injected result-model construction failure")

    monkeypatch.setattr(
        generation_module,
        "AcademicResultManifestGenerationResult",
        fail_result_model,
    )
    with pytest.raises(ScoreFormManifestGenerationPartialSuccessError) as caught:
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    error = caught.value
    assert error.state.durable_file_exists
    assert error.state.path.read_bytes()
    assert isinstance(error.__cause__, RuntimeError)
    assert not (paths.academic_result_manifests_dir / ".write.lock").exists()
