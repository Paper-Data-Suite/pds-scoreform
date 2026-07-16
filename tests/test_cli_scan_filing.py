"""PDS2 page dispatch remains isolated from assignment-local scan filing."""

import scoreform.cli


def test_qr_scoring_file_failure_does_not_claim_export(capsys) -> None:
    assert scoreform.cli.main(["score", "scan.pdf"]) == 1

    output = capsys.readouterr().out
    assert "Status: file_failure" in output
    assert "pending #144" not in output
