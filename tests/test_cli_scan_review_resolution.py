"""Direct CLI scan-review error coverage."""

import scoreform.cli


def test_unknown_scan_review_resolution_fails_cleanly(capsys) -> None:
    assert (
        scoreform.cli.main(["resolve-scan-review", "failure1", "--action", "defer"])
        == 1
    )

    output = capsys.readouterr().out
    assert "Unknown ScoreForm scan review item" in output
