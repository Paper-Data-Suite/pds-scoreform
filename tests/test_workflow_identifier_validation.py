from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pds_core.class_metadata import (
    create_class_metadata,
    load_class_metadata_for_class,
    write_class_metadata_for_class,
)
from pds_core.classes import ClassFolder
from pds_core.rosters import Roster as CoreRoster
from pds_core.rosters import RosterWriteError, StudentRecord
from pds_core.school_years import open_school_year

from scoreform import roster, workflows


@dataclass(frozen=True)
class AssignmentFolder:
    """Legacy fixture shape used by isolated workflow-helper tests."""

    class_id: str
    assignment_id: str
    class_dir: Path
    assignments_dir: Path
    assignment_dir: Path


def test_print_menu_header_uses_plain_text_for_captured_output(capsys):
    workflows.print_menu_header("Example Workflow")

    assert capsys.readouterr().out == "ScoreForm\nExample Workflow\n\n"


def test_print_menu_header_uses_restrained_green_when_color_is_supported(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(workflows, "_stdout_supports_color", lambda: True)

    workflows.print_menu_header("Example Workflow")

    output = capsys.readouterr().out
    assert output == "\x1b[32mScoreForm\x1b[0m\nExample Workflow\n\n"
    assert "\x1b[34m" not in output
    assert "\x1b[36m" not in output


def test_suggest_class_id_examples():
    assert workflows.suggest_class_id("English 9 Period 2") == "english_9_period_2"
    assert workflows.suggest_class_id("English 12 P5") == "english_12_p5"
    assert workflows.suggest_class_id("AP Computer Science") == "ap_computer_science"
    assert workflows.suggest_class_id("English-12 / Period 3") == "english-12_period_3"
    assert workflows.suggest_class_id("Extra   Spaces") == "extra_spaces"
    assert workflows.suggest_class_id("!!!") == ""


def test_suggest_assignment_id_examples():
    assert workflows.suggest_assignment_id("Romeo and Juliet Act 1 Quiz") == "romeo_and_juliet_act_1_quiz"
    assert workflows.suggest_assignment_id("AP CSP Unit 3 Test") == "ap_csp_unit_3_test"
    assert workflows.suggest_assignment_id("No Country / There Will Be Blood") == "no_country_there_will_be_blood"
    assert workflows.suggest_assignment_id("Essay: Hero's Journey") == "essay_heros_journey"
    assert workflows.suggest_assignment_id("Extra   Spaces") == "extra_spaces"
    assert workflows.suggest_assignment_id("!!!") == ""


def test_discover_class_rosters_finds_valid_rosters_deterministically(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "classes" / "z_class").mkdir(parents=True)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "z_class" / "roster.csv"),
        "z_class",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "a_class" / "roster.csv"),
        "a_class",
        "2",
        [{"student_id": "1002", "last_name": "Smith", "first_name": "Marcus"}],
    )
    (tmp_path / "classes" / "no_roster").mkdir()
    (tmp_path / "classes" / "bad_class").mkdir()
    (tmp_path / "classes" / "bad_class" / "roster.csv").write_text("not,a,roster\n", encoding="utf-8")

    discovered = workflows.discover_class_rosters()

    assert [item["class_id"] for item in discovered] == ["a_class", "z_class"]


def test_discover_class_rosters_includes_optional_class_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english9_p2" / "roster.csv"),
        "english9_p2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    write_class_metadata_for_class(
        tmp_path,
        create_class_metadata(
            "english9_p2",
            "2026-2027",
            created_at=datetime.now(timezone.utc),
        ),
    )

    [record] = workflows.discover_class_rosters()

    assert record["metadata_path"] == str(
        tmp_path / "classes" / "english9_p2" / "class.json"
    )
    assert record["school_year"] == "2026-2027"
    assert record["metadata_error"] is None


def test_discover_class_rosters_reports_invalid_metadata_without_hiding_roster(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english9_p2" / "roster.csv"),
        "english9_p2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    metadata_path = tmp_path / "classes" / "english9_p2" / "class.json"
    metadata_path.write_text('{"school_year": "2026-2028"}\n', encoding="utf-8")

    [record] = workflows.discover_class_rosters()

    assert record["class_id"] == "english9_p2"
    assert record["school_year"] is None
    assert record["metadata_error"]


def test_discover_class_rosters_uses_core_class_folder_discovery(
    tmp_path,
    monkeypatch,
):
    roster_path = tmp_path / "classes" / "english9_p2" / "roster.csv"
    core_roster = CoreRoster(
        class_id="english9_p2",
        students=(
            StudentRecord(
                class_id="english9_p2",
                student_id="0012",
                last_name="Doe",
                first_name="Jane",
                period="2",
                extra_fields={"preferred_name": "Janey", "email": ""},
            ),
        ),
        columns=(
            "class_id",
            "student_id",
            "last_name",
            "first_name",
            "period",
            "preferred_name",
            "email",
        ),
        source_path=roster_path,
    )
    core_folder = ClassFolder(
        class_id="english9_p2",
        class_dir=roster_path.parent,
        roster_path=roster_path,
        metadata_path=roster_path.parent / "class.json",
        roster=core_roster,
    )
    calls = []

    def fake_list_class_folders(
        workspace_root,
        *,
        require_roster=False,
        load_rosters=False,
    ):
        calls.append((workspace_root, require_roster, load_rosters))
        return (core_folder,)

    monkeypatch.setattr(
        workflows,
        "list_core_class_folders",
        fake_list_class_folders,
    )

    discovered = workflows.discover_class_rosters()

    assert calls == [(Path(tmp_path), True, True)]
    assert discovered == [
        {
            "class_id": "english9_p2",
            "roster_path": str(roster_path),
            "metadata_path": str(roster_path.parent / "class.json"),
            "school_year": None,
            "metadata_error": None,
            "roster": {
                "class_id": "english9_p2",
                "roster_path": str(roster_path),
                "students": [
                    {
                        "class_id": "english9_p2",
                        "student_id": "0012",
                        "last_name": "Doe",
                        "first_name": "Jane",
                        "period": "2",
                        "preferred_name": "Janey",
                        "email": "",
                    }
                ],
            },
        }
    ]


def test_discover_class_rosters_accepts_explicit_workspace_root(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(
        workflows,
        "list_core_class_folders",
        lambda workspace_root, **kwargs: calls.append(
            (workspace_root, kwargs)
        ) or (),
    )

    assert workflows.discover_class_rosters(tmp_path) == []
    assert calls == [
        (
            tmp_path,
            {"require_roster": True, "load_rosters": True},
        )
    ]


def test_discover_class_rosters_missing_workspace_classes_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert workflows.discover_class_rosters() == []


def test_discover_class_rosters_ignores_mismatched_folder_and_roster_class_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "folder_id" / "roster.csv"),
        "roster_id",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )

    assert workflows.discover_class_rosters() == []


def test_parse_single_selection_accepts_one_valid_numeric_selection():
    available = [{"id": "a"}, {"id": "b"}]

    assert workflows.parse_single_selection("1", available, "item") == available[0]
    assert workflows.parse_single_selection(" 2 ", available, "item") == available[1]


def test_parse_single_selection_rejects_empty_invalid_and_out_of_range():
    available = [{"id": "a"}, {"id": "b"}]

    for selection in ["", " ", "x", "1,2", "0", "3"]:
        try:
            workflows.parse_single_selection(selection, available, "item")
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for selection {selection!r}")


def test_parse_class_selection_accepts_single_multiple_whitespace_and_duplicates():
    available = [{"class_id": "a"}, {"class_id": "b"}, {"class_id": "c"}]

    assert workflows.parse_class_selection("1", available) == [available[0]]
    assert workflows.parse_class_selection("1,3", available) == [available[0], available[2]]
    assert workflows.parse_class_selection(" 2 , 3 ", available) == [available[1], available[2]]
    assert workflows.parse_class_selection("2,2,1", available) == [available[1], available[0]]


def test_parse_class_selection_rejects_empty_invalid_and_out_of_range():
    available = [{"class_id": "a"}, {"class_id": "b"}]

    for selection in ["", " ", "1,", "x", "0", "3"]:
        try:
            workflows.parse_class_selection(selection, available)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for selection {selection!r}")


def test_format_roster_for_display_includes_summary_rows_and_optional_columns():
    class_record = {
        "class_id": "english_9_period_2",
        "roster_path": "classes/english_9_period_2/roster.csv",
        "roster": {
            "students": [
                {
                    "class_id": "english_9_period_2",
                    "student_id": "1001",
                    "last_name": "Doe",
                    "first_name": "Jane",
                    "period": "2",
                    "preferred_name": "Janie",
                },
                {
                    "class_id": "english_9_period_2",
                    "student_id": "1002",
                    "last_name": "Smith",
                    "first_name": "Marcus",
                    "period": "2",
                    "preferred_name": "",
                },
            ],
        },
    }

    output = workflows.format_roster_for_display(class_record)

    assert "Class: english_9_period_2" in output
    assert "School year: not set" in output
    assert "Roster: classes/english_9_period_2/roster.csv" in output
    assert "Class metadata: not set" in output
    assert "Students: 2" in output
    assert "student_id" in output
    assert "last_name" in output
    assert "first_name" in output
    assert "period" in output
    assert "preferred_name" in output
    assert "1001" in output
    assert "Doe" in output
    assert "Jane" in output


def test_format_roster_for_display_includes_class_metadata():
    class_record = {
        "class_id": "english_9_period_2",
        "roster_path": "classes/english_9_period_2/roster.csv",
        "metadata_path": "classes/english_9_period_2/class.json",
        "school_year": "2026-2027",
        "metadata_error": None,
        "roster": {"students": []},
    }

    output = workflows.format_roster_for_display(class_record)

    assert "School year: 2026-2027" in output
    assert "Class metadata: classes/english_9_period_2/class.json" in output


def test_format_roster_for_display_reports_metadata_error():
    class_record = {
        "class_id": "english_9_period_2",
        "roster_path": "classes/english_9_period_2/roster.csv",
        "metadata_path": "classes/english_9_period_2/class.json",
        "school_year": None,
        "metadata_error": "bad metadata",
        "roster": {"students": []},
    }

    output = workflows.format_roster_for_display(class_record)

    assert "School year: metadata error" in output
    assert "Metadata error: bad metadata" in output


def test_prompt_view_roster_handles_no_available_rosters(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert workflows.prompt_view_roster() == 1

    output = capsys.readouterr().out
    assert "No class rosters found." in output
    assert "Create a class roster first" in output


def test_prompt_view_roster_displays_selected_class_roster(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english_9_period_2" / "roster.csv"),
        "english_9_period_2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english_12_p5" / "roster.csv"),
        "english_12_p5",
        "5",
        [{"student_id": "1002", "last_name": "Smith", "first_name": "Marcus"}],
    )
    responses = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    monkeypatch.setattr(workflows, "clear_screen", lambda: print("<CLEAR>"))

    assert workflows.prompt_view_roster() == 0

    output = capsys.readouterr().out
    assert "Available classes:" in output
    assert "1. english_12_p5" in output
    assert "2. english_9_period_2" in output
    assert "Class: english_9_period_2" in output
    assert f"Roster: {tmp_path / 'classes'}" in output
    assert "Students: 1" in output
    assert "1001" in output
    assert "Doe" in output
    assert "Jane" in output
    detail_screen = next(
        screen
        for screen in output.split("<CLEAR>")
        if "Roster:" in screen and "Students: 1" in screen
    )
    assert "Available classes:" not in detail_screen
    assert "Select class:" not in detail_screen


def test_prompt_view_roster_rejects_invalid_selection(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english_9_period_2" / "roster.csv"),
        "english_9_period_2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    responses = iter(["3"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_view_roster() == 1

    output = capsys.readouterr().out
    assert "Error: Class selection out of range: 3" in output


def test_write_roster_csv_rejects_unsafe_class_id(tmp_path):
    output_path = tmp_path / "roster.csv"
    students = [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}]

    assert not workflows.write_roster_csv(str(output_path), "../secret", "2", students)
    assert not output_path.exists()


def test_write_roster_csv_rejects_unsafe_student_id(tmp_path):
    output_path = tmp_path / "roster.csv"
    students = [{"student_id": "classes/foo", "last_name": "Doe", "first_name": "Jane"}]

    assert not workflows.write_roster_csv(str(output_path), "english9_p2", "2", students)
    assert not output_path.exists()


def test_write_roster_csv_uses_core_roster_writer(tmp_path, monkeypatch):
    output_path = tmp_path / "classes" / "english9_p2" / "roster.csv"
    students = [
        {"student_id": "0012", "last_name": "Doe", "first_name": "Jane"},
        {"student_id": "1002", "last_name": "Smith", "first_name": "Marcus"},
    ]
    core_roster = object()
    calls = []

    def fake_create_core_roster(class_id, rows):
        calls.append(("create", class_id, rows))
        return core_roster

    def fake_write_core_roster(path, roster, *, overwrite=False):
        calls.append(("write", path, roster, overwrite))

    monkeypatch.setattr(workflows, "create_core_roster", fake_create_core_roster)
    monkeypatch.setattr(workflows, "write_core_roster", fake_write_core_roster)

    assert workflows.write_roster_csv(
        str(output_path),
        "english9_p2",
        "2",
        students,
    )
    assert output_path.parent.is_dir()
    assert calls == [
        (
            "create",
            "english9_p2",
            [
                {
                    "student_id": "0012",
                    "last_name": "Doe",
                    "first_name": "Jane",
                    "period": "2",
                },
                {
                    "student_id": "1002",
                    "last_name": "Smith",
                    "first_name": "Marcus",
                    "period": "2",
                },
            ],
        ),
        ("write", str(output_path), core_roster, True),
    ]


def test_write_roster_csv_writes_minimal_scoreform_roster_csv(tmp_path):
    output_path = tmp_path / "roster.csv"

    assert workflows.write_roster_csv(
        str(output_path),
        "english9_p2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "class_id,student_id,last_name,first_name,period",
        "english9_p2,1001,Doe,Jane,2",
    ]


def test_write_roster_csv_creates_parent_directory(tmp_path):
    output_path = tmp_path / "classes" / "english9_p2" / "roster.csv"

    assert workflows.write_roster_csv(
        str(output_path),
        "english9_p2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    assert output_path.parent.is_dir()
    assert output_path.is_file()


def test_write_roster_csv_preserves_student_order_and_leading_zero_ids(tmp_path):
    output_path = tmp_path / "roster.csv"
    students = [
        {"student_id": "0012", "last_name": "Doe", "first_name": "Jane"},
        {"student_id": "1001", "last_name": "Smith", "first_name": "Marcus"},
    ]

    assert workflows.write_roster_csv(
        str(output_path),
        "english9_p2",
        "2",
        students,
    )
    loaded = roster.load_roster(str(output_path))
    assert loaded is not None
    assert [student["student_id"] for student in loaded["students"]] == [
        "0012",
        "1001",
    ]


def test_write_roster_csv_returns_false_on_core_write_error(
    tmp_path,
    monkeypatch,
):
    output_path = tmp_path / "roster.csv"

    def fail_write(path, roster, *, overwrite=False):
        raise RosterWriteError(path, "test write failure")

    monkeypatch.setattr(workflows, "write_core_roster", fail_write)

    assert not workflows.write_roster_csv(
        str(output_path),
        "english9_p2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )


def test_write_assignment_json_rejects_unsafe_assignment_id(tmp_path):
    output_path = tmp_path / "assignment.json"
    assignment = {
        "assignment_id": r"C:\Users\Teacher",
        "title": "Unsafe",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }

    assert not workflows.write_assignment_json(str(output_path), assignment)
    assert not output_path.exists()


def test_prompt_create_roster_rejects_unsafe_class_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "!!!",
        "classes/foo",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert not (tmp_path / "classes" / "classes" / "foo" / "roster.csv").exists()


def test_prompt_create_roster_rejects_unsafe_student_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "English 9 Period 2",
        "",
        "2026-2027",
        "2",
        "../secret",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert not (tmp_path / "classes" / "english_9_period_2" / "roster.csv").exists()


def test_prompt_create_roster_writes_class_centered_roster(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "English 9 Period 2",
        "",
        "2026-2027",
        "2",
        "1001",
        "Doe",
        "Jane",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 0

    output_path = tmp_path / "classes" / "english_9_period_2" / "roster.csv"
    metadata_path = tmp_path / "classes" / "english_9_period_2" / "class.json"
    assert output_path.exists()
    assert metadata_path.exists()
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "class_id,student_id,last_name,first_name,period",
        "english_9_period_2,1001,Doe,Jane,2",
    ]
    metadata = load_class_metadata_for_class(tmp_path, "english_9_period_2")
    assert metadata.school_year == "2026-2027"

    loaded = roster.load_roster(str(output_path))
    assert loaded is not None
    assert loaded["class_id"] == "english_9_period_2"
    assert len(loaded["students"]) == 1


def test_prompt_create_roster_accepts_active_school_year(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.now(timezone.utc),
    )
    responses = iter([
        "English 9 Period 2",
        "",
        "",
        "2",
        "1001",
        "Doe",
        "Jane",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 0

    metadata = load_class_metadata_for_class(tmp_path, "english_9_period_2")
    assert metadata.school_year == "2026-2027"
    output = capsys.readouterr().out
    assert "Active school year: 2026-2027" in output


def test_prompt_create_roster_rejects_invalid_school_year(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "English 9 Period 2",
        "",
        "2026-2028",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert not (tmp_path / "classes" / "english_9_period_2" / "roster.csv").exists()
    assert not (tmp_path / "classes" / "english_9_period_2" / "class.json").exists()


def test_roster_menu_create_class_roster_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "1",
        "English 12 P5",
        "",
        "2026-2027",
        "5",
        "1002",
        "Smith",
        "Marcus",
        "n",
        "",
        "5",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.launch_roster_menu() == 0

    output_path = tmp_path / "classes" / "english_12_p5" / "roster.csv"
    loaded = roster.load_roster(str(output_path))
    assert loaded is not None
    assert loaded["class_id"] == "english_12_p5"
    assert loaded["students"][0]["student_id"] == "1002"


def test_roster_menu_view_class_roster_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english_9_period_2" / "roster.csv"),
        "english_9_period_2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    responses = iter(["2", "1", "", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.launch_roster_menu() == 0

    output = capsys.readouterr().out
    assert "2. View a class roster" in output
    assert "3. Edit class roster" in output
    assert "4. Validate a roster file" in output
    assert "Class: english_9_period_2" in output
    assert "Students: 1" in output
    assert "1001" in output


def test_roster_menu_clears_for_submenu_and_pauses_after_view(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english_9_period_2" / "roster.csv"),
        "english_9_period_2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    calls = []
    responses = iter(["2", "1", "5"])

    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    monkeypatch.setattr(workflows, "clear_screen", lambda: calls.append("clear"))
    monkeypatch.setattr(workflows, "pause_for_user", lambda: calls.append("pause"))

    assert workflows.launch_roster_menu() == 0

    assert calls.count("clear") >= 3
    assert "pause" in calls


def test_prompt_create_roster_does_not_overwrite_without_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output_path = tmp_path / "classes" / "english_9_period_2" / "roster.csv"
    output_path.parent.mkdir(parents=True)
    original_content = (
        "class_id,student_id,last_name,first_name,period\n"
        "english_9_period_2,1001,Doe,Jane,2\n"
    )
    output_path.write_text(original_content, encoding="utf-8")
    responses = iter([
        "English 9 Period 2",
        "",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert output_path.read_text(encoding="utf-8") == original_content
