"""Interim regeneration boundaries for migration issues #139-#141."""

import scoreform.cli


def test_regeneration_command_fails_cleanly(capsys) -> None:
    assert (
        scoreform.cli.main(
            ["regenerate-sheets", "--class-id", "class1", "--all-assignments"]
        )
        == 1
    )

    output = capsys.readouterr().out
    assert "#139 through #141" in output
    assert "temporarily unavailable" in output
