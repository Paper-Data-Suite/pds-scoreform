from pathlib import Path

from scoreform import cli, cli_score


class Results(list):
    def __init__(self, values=None, summary="summary"):
        super().__init__(values or [])
        self.summary = summary


def _result():
    return {
        "page_num": 1,
        "class_id": "english9_p2",
        "assignment_id": "rj_act1_quiz",
        "student_id": "1001",
        "score": 1,
        "total_points": 1,
        "answers": [{"Q": 1, "Answer": "A", "Correct": True}],
    }


def test_qr_aware_no_scored_pages_prints_and_saves_summary(
    tmp_path,
    monkeypatch,
    capsys,
):
    calls = []
    results = Results()

    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: calls.append(
            ("process", input_file, workspace_root)
        )
        or results,
    )
    monkeypatch.setattr(
        cli_score,
        "get_qr_batch_summary",
        lambda all_results: calls.append(("summary", all_results)) or all_results.summary,
    )
    monkeypatch.setattr(
        cli_score,
        "print_qr_batch_summary",
        lambda summary: calls.append(("print_summary", summary)),
    )
    monkeypatch.setattr(
        cli_score,
        "save_qr_batch_summary",
        lambda summary, source, workspace_root=None: calls.append(
            ("save_summary", summary, source, workspace_root)
        ),
    )

    assert cli_score.run_score(["scan.pdf"]) == 1

    assert calls == [
        ("process", "scan.pdf", tmp_path),
        ("summary", results),
        ("print_summary", "summary"),
        ("save_summary", "summary", "scan.pdf", tmp_path),
    ]
    assert "Error: No pages were scored successfully." in capsys.readouterr().out


def test_qr_aware_export_failure_updates_summary_and_skips_filing(
    tmp_path,
    monkeypatch,
    capsys,
):
    calls = []
    results = Results([_result()])

    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: results,
    )
    monkeypatch.setattr(
        cli_score,
        "export_routed_results",
        lambda all_results, workspace_root=None: False,
    )
    monkeypatch.setattr(
        cli_score,
        "update_qr_batch_result_write_status",
        lambda all_results,
        export_success,
        output_file=None,
        workspace_root=None: calls.append(
            (
                "write_status",
                all_results,
                export_success,
                output_file,
                workspace_root,
            )
        ),
    )
    monkeypatch.setattr(
        cli_score,
        "get_qr_batch_summary",
        lambda all_results: calls.append(("summary", all_results)) or all_results.summary,
    )
    monkeypatch.setattr(
        cli_score,
        "print_qr_batch_summary",
        lambda summary: calls.append(("print_summary", summary)),
    )
    monkeypatch.setattr(
        cli_score,
        "save_qr_batch_summary",
        lambda summary, source, workspace_root=None: calls.append(
            ("save_summary", summary, source, workspace_root)
        ),
    )
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_copy",
        lambda all_results, source, workspace_root=None: calls.append(
            ("file", all_results, source, workspace_root)
        ),
    )

    assert cli_score.run_score(["scan.pdf"]) == 1

    assert calls == [
        ("write_status", results, False, None, tmp_path),
        ("summary", results),
        ("print_summary", "summary"),
        ("save_summary", "summary", "scan.pdf", tmp_path),
    ]
    assert "Error: Failed to export results." in capsys.readouterr().out


def test_main_score_dispatch_still_routes_to_cli_run_score(monkeypatch):
    calls = []

    monkeypatch.setattr(cli, "run_score", lambda args: calls.append(args) or 0)

    assert cli.main(["score", "scan.pdf", "out.csv"]) == 0
    assert calls == [["scan.pdf", "out.csv"]]


def test_cli_score_does_not_use_signature_reflection():
    source = Path(cli_score.__file__).resolve().read_text(encoding="utf-8")

    assert "inspect.signature" not in source
    assert "_call_with_workspace_root" not in source
