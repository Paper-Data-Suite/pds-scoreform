import json
from datetime import datetime

from pds_core.school_years import (
    get_active_school_year,
    load_school_year_state,
    open_school_year,
    school_year_state_path,
)

import scoreform.cli


def test_school_year_help_forms_and_top_level_help(capsys):
    for args in (
        ["school-year", "help"],
        ["school-year", "--help"],
        ["school-year", "-h"],
    ):
        assert scoreform.cli.main(args) == 0
        output = capsys.readouterr().out
        assert "scoreform school-year show" in output
        assert "scoreform school-year open <school_year> [--overwrite]" in output
        assert "scoreform school-year close" in output

    assert scoreform.cli.main(["--help"]) == 0
    output = capsys.readouterr().out
    assert "school-year" in output
    assert "scoreform school-year show" in output


def test_school_year_show_reports_missing_open_and_closed_states(tmp_path, capsys):
    assert scoreform.cli.main(["school-year", "show"]) == 0
    output = capsys.readouterr().out
    assert "No school year has been opened" in output

    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )
    assert scoreform.cli.main(["school-year", "show"]) == 0
    output = capsys.readouterr().out
    assert "Active school year: 2026-2027" in output
    assert "Opened at: 2020-08-28T09:00:00-04:00" in output

    assert scoreform.cli.main(["school-year", "close"]) == 0
    capsys.readouterr()
    assert scoreform.cli.main(["school-year", "show"]) == 0
    output = capsys.readouterr().out
    assert "No active school year is open." in output
    assert "Last school year: 2026-2027" in output
    assert "Closed at:" in output


def test_school_year_show_malformed_state_returns_error(tmp_path, capsys):
    path = school_year_state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")

    assert scoreform.cli.main(["school-year", "show"]) == 1
    output = capsys.readouterr().out
    assert "Error:" in output
    assert "invalid JSON" in output


def test_school_year_open_creates_loadable_timezone_aware_state(tmp_path, capsys):
    assert scoreform.cli.main(["school-year", "open", "2026-2027"]) == 0
    output = capsys.readouterr().out
    assert "Opened school year: 2026-2027" in output

    state = load_school_year_state(tmp_path)
    assert state is not None
    assert state.active_school_year == "2026-2027"
    assert state.opened_at.tzinfo is not None
    assert state.opened_at.utcoffset() is not None
    assert school_year_state_path(tmp_path).is_file()


def test_school_year_open_same_year_is_success(tmp_path, capsys):
    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )

    assert scoreform.cli.main(["school-year", "open", "2026-2027"]) == 0
    assert "School year is already open: 2026-2027" in capsys.readouterr().out


def test_school_year_open_invalid_and_argument_errors(capsys):
    invalid_forms = (
        ["school-year", "open"],
        ["school-year", "open", "2026-2027", "extra"],
        ["school-year", "open", "--overwrite"],
        ["school-year", "open", "2026-2027", "--bad-flag"],
    )

    for args in invalid_forms:
        assert scoreform.cli.main(args) == 1
        assert "Usage: scoreform school-year open" in capsys.readouterr().out

    assert scoreform.cli.main(["school-year", "open", "2026-2028"]) == 1
    output = capsys.readouterr().out
    assert "Error:" in output
    assert "school_year" in output


def test_school_year_open_different_year_requires_overwrite(tmp_path, capsys):
    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )

    assert scoreform.cli.main(["school-year", "open", "2027-2028"]) == 1
    output = capsys.readouterr().out
    assert "Error:" in output
    assert "different school year is already open" in output
    assert get_active_school_year(tmp_path) == "2026-2027"

    assert scoreform.cli.main([
        "school-year",
        "open",
        "2027-2028",
        "--overwrite",
    ]) == 0
    output = capsys.readouterr().out
    assert "Replaced active school year with: 2027-2028" in output
    assert get_active_school_year(tmp_path) == "2027-2028"


def test_school_year_close_closes_open_year_with_aware_timestamp(tmp_path, capsys):
    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )

    assert scoreform.cli.main(["school-year", "close"]) == 0
    output = capsys.readouterr().out
    assert "Closed school year: 2026-2027" in output

    state = load_school_year_state(tmp_path)
    assert state is not None
    assert state.closed_at is not None
    assert state.closed_at.tzinfo is not None
    assert state.closed_at.utcoffset() is not None
    assert get_active_school_year(tmp_path) is None


def test_school_year_close_error_cases(tmp_path, capsys):
    assert scoreform.cli.main(["school-year", "close"]) == 1
    assert "No school year is open" in capsys.readouterr().out

    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )
    assert scoreform.cli.main(["school-year", "close", "extra"]) == 1
    assert "Usage: scoreform school-year close" in capsys.readouterr().out

    assert scoreform.cli.main(["school-year", "close"]) == 0
    capsys.readouterr()
    assert scoreform.cli.main(["school-year", "close"]) == 1
    assert "already closed" in capsys.readouterr().out


def test_school_year_workflows_only_create_settings_state(tmp_path):
    assert scoreform.cli.main(["school-year", "open", "2026-2027"]) == 0

    created_paths = {
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
    }
    assert created_paths == {
        "settings",
        "settings/school_year.json",
    }
    assert json.loads(school_year_state_path(tmp_path).read_text(encoding="utf-8"))[
        "active_school_year"
    ] == "2026-2027"

