from __future__ import annotations

from pathlib import Path

from scoreform import cli_score
from scoreform.attempt_assembly import (
    ScoreFormAttemptAssemblyBatch,
    ScoreFormRoutedScoringBatch,
)
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.scan_review_models import ScoreFormFailurePersistenceBatch


def _file_failure_models():
    dispatch = Pds2ScanDispatchResult(
        retained_source=None,
        file_error=FileNotFoundError("synthetic missing scan"),
    )
    assembly = ScoreFormAttemptAssemblyBatch(dispatch)
    review = ScoreFormFailurePersistenceBatch()
    return dispatch, assembly, review


def test_structured_routed_operation_preserves_exact_models_and_exit_semantics(
    monkeypatch, tmp_path: Path
) -> None:
    dispatch, assembly, review = _file_failure_models()
    calls: list[str] = []

    def process(*_args, **_kwargs):
        calls.append("dispatch")
        return dispatch

    def assemble(actual_dispatch, **_kwargs):
        calls.append("assembly")
        assert actual_dispatch is dispatch
        return assembly

    def persist(actual_batch, *_args, **_kwargs):
        calls.append("review")
        assert isinstance(actual_batch, ScoreFormRoutedScoringBatch)
        assert actual_batch.dispatch_result is dispatch
        assert actual_batch.assembly_result is assembly
        return review

    monkeypatch.setattr(cli_score, "process_pds2_scan", process)
    monkeypatch.setattr(cli_score, "assemble_scoreform_attempts", assemble)
    monkeypatch.setattr(cli_score, "persist_routed_scoring_failures", persist)
    monkeypatch.setattr(
        cli_score,
        "export_scoreform_attempts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("file-failure operation must not export")
        ),
    )
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_after_success",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("file-failure operation must not file a scan")
        ),
    )

    result = cli_score.execute_routed_scoring_operation(
        "scan.pdf",
        workspace_root=tmp_path,
    )

    assert result.operation_error is None
    assert result.batch is not None
    assert result.batch.dispatch_result is dispatch
    assert result.batch.assembly_result is assembly
    assert result.review is review
    assert result.scan_filing is None
    assert result.exit_code == 1
    assert calls == ["dispatch", "assembly", "review"]


def test_invalid_dispatch_is_a_structured_terminal_failure(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli_score, "process_pds2_scan", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        cli_score,
        "assemble_scoreform_attempts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid dispatch must stop before assembly")
        ),
    )

    result = cli_score.execute_routed_scoring_operation(
        "scan.pdf",
        workspace_root=tmp_path,
    )

    assert result.batch is None
    assert result.review is None
    assert result.scan_filing is None
    assert result.exit_code == 1
    assert result.operation_error == (
        "PDS2 scan processing returned an invalid batch result."
    )

    cli_score._print_routed_scoring_operation(result)
    assert capsys.readouterr().out == (
        "Error: PDS2 scan processing returned an invalid batch result.\n"
    )


def test_direct_routed_wrapper_renders_existing_summaries_from_structured_result(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    dispatch, assembly, review = _file_failure_models()
    result = cli_score.RoutedScoringOperationResult(
        batch=ScoreFormRoutedScoringBatch(dispatch, assembly),
        review=review,
    )

    monkeypatch.setattr(
        cli_score,
        "execute_routed_scoring_operation",
        lambda *_args, **_kwargs: result,
    )
    monkeypatch.setattr(
        cli_score,
        "format_pds2_dispatch_summary",
        lambda actual: "dispatch summary" if actual is dispatch else "wrong dispatch",
    )
    monkeypatch.setattr(
        cli_score,
        "format_routed_scoring_summary",
        lambda actual: "routed summary" if actual is result.batch else "wrong batch",
    )

    assert cli_score._run_routed_scoring(
        "scan.pdf",
        workspace_root=tmp_path,
    ) == 1
    assert capsys.readouterr().out == "dispatch summary\nrouted summary\n"
