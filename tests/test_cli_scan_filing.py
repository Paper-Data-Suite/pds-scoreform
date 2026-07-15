"""PDS2 page dispatch remains isolated from assignment-local scan filing."""

import scoreform.cli


def test_qr_scoring_does_not_claim_scan_filing_or_export(capsys) -> None:
    assert scoreform.cli.main(["score", "scan.pdf"]) == 1

    output = capsys.readouterr().out
    assert "pending #144" in output
    assert "No routed results were written" in output
