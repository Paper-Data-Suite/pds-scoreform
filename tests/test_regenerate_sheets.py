"""Regeneration is operational and reports ordinary managed-source errors."""

import scoreform.cli


def test_regeneration_command_reports_missing_managed_roster(capsys) -> None:
    assert (
        scoreform.cli.main(
            ["regenerate-sheets", "--class-id", "class1", "--all-assignments"]
        )
        == 1
    )

    output = capsys.readouterr().out
    assert "Managed roster not found" in output
    assert "#141" not in output
