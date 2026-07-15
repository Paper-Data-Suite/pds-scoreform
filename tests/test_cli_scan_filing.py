"""QR-aware scoring remains gated before post-success scan filing (#143)."""

import scoreform.cli


def test_qr_scoring_fails_cleanly_before_scan_filing(capsys) -> None:
    assert scoreform.cli.main(["score", "scan.pdf"]) == 1

    output = capsys.readouterr().out
    assert "#143" in output
    assert "temporarily unavailable" in output
