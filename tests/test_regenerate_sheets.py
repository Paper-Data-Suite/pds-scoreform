"""Regeneration remains gated on page and route records."""

import scoreform.cli


def test_regeneration_command_fails_cleanly(capsys) -> None:
    assert (
        scoreform.cli.main(
            ["regenerate-sheets", "--class-id", "class1", "--all-assignments"]
        )
        == 1
    )

    output = capsys.readouterr().out
    assert "#140 and #141" in output
    assert "temporarily unavailable" in output
