"""Interim CLI boundary coverage for scan-review migration issue #145."""

import scoreform.cli


def test_scan_review_resolution_fails_cleanly(capsys) -> None:
    assert (
        scoreform.cli.main(
            ["resolve-scan-review", "failure1", "--action", "defer"]
        )
        == 1
    )

    output = capsys.readouterr().out
    assert "#145" in output
    assert "temporarily unavailable" in output
