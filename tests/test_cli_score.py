from __future__ import annotations

from scoreform import cli, cli_score
from scoreform.scoring import ManualScoringResults, ManualScoringSummary


def test_qr_aware_scoring_is_enabled_and_missing_source_fails_cleanly(capsys) -> None:
    assert cli.main(["score", "scan.pdf"]) == 1
    output = capsys.readouterr().out
    assert "retained PDS2 Core dispatch mode" in output
    assert "Source file does not exist" in output
    assert "Status: file_failure" in output
    assert "pending #144" not in output


def test_manual_explicit_answer_key_scoring_remains_available(monkeypatch, tmp_path) -> None:
    output = tmp_path / "results.csv"
    answer_key = tmp_path / "answer_key.json"
    answer_key.write_text('{"1": "A"}', encoding="utf-8")
    results = ManualScoringResults(
        [{"page": 1, "score": 1, "total_points": 1, "answers": []}],
        summary=ManualScoringSummary(pages_processed=1, pages_scored=1),
    )
    monkeypatch.setattr(cli_score, "process_file", lambda *_args: results)
    monkeypatch.setattr(cli_score, "export_to_csv", lambda *_args, **_kwargs: True)

    assert cli_score.run_score(["scan.pdf", output, answer_key]) == 0


def test_main_score_dispatch_still_routes_to_cli_run_score(monkeypatch) -> None:
    calls = []

    def fake_run_score(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(cli, "run_score", fake_run_score)
    assert cli.main(["score", "scan.pdf", "answer_key.json"]) == 0
    assert calls == [["scan.pdf", "answer_key.json"]]
