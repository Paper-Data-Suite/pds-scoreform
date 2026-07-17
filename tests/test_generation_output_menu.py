from pathlib import Path

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from scoreform import generate_workflows


def test_assignment_actions_offer_required_choices_and_open_exact_paths(
    tmp_path, monkeypatch, capsys
):
    packet = tmp_path / "class packet.pdf"
    individual = tmp_path / "individual sheets"
    opened = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda root, path: opened.append((root, Path(path))) or Path(path),
    )

    generate_workflows._offer_assignment_output_actions(
        tmp_path, packet, individual
    )

    output = capsys.readouterr().out
    assert "1. Open class packet for printing" in output
    assert "2. Open individual answer sheets folder" in output
    assert "3. Return" in output
    assert opened == [(tmp_path, packet)]


def test_assignment_option_two_opens_exact_individual_directory(
    tmp_path, monkeypatch
):
    packet = tmp_path / "class packet.pdf"
    individual = tmp_path / "individual sheets"
    opened = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda root, path: opened.append((root, Path(path))) or Path(path),
    )

    generate_workflows._offer_assignment_output_actions(
        tmp_path, packet, individual
    )

    assert opened == [(tmp_path, individual)]


def test_invalid_assignment_action_uses_navigation_error_then_allows_return(
    tmp_path, monkeypatch, capsys
):
    responses = iter(("9", "3"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    generate_workflows._offer_assignment_output_actions(
        tmp_path, tmp_path / "packet.pdf", tmp_path / "individual"
    )

    output = capsys.readouterr().out
    assert "Invalid selection: 9." in output
    assert "Please choose a listed option, B, M, or Q." in output


@pytest.mark.parametrize("selection", ("", "3", "b"))
def test_blank_return_and_navigation_open_nothing(tmp_path, monkeypatch, selection):
    monkeypatch.setattr("builtins.input", lambda _prompt="": selection)
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda *_args: pytest.fail("file opening was not expected"),
    )
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda *_args: pytest.fail("folder opening was not expected"),
    )

    generate_workflows._offer_assignment_output_actions(
        tmp_path, tmp_path / "packet.pdf", tmp_path / "individual"
    )


@pytest.mark.parametrize(
    ("selection", "navigation_error"),
    (("m", ReturnToMainMenu), ("q", QuitPDS)),
)
def test_main_and_quit_navigation_propagate_without_opening(
    tmp_path, monkeypatch, selection, navigation_error
):
    monkeypatch.setattr("builtins.input", lambda _prompt="": selection)
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda *_args: pytest.fail("file opening was not expected"),
    )

    with pytest.raises(navigation_error):
        generate_workflows._offer_assignment_output_actions(
            tmp_path, tmp_path / "packet.pdf", tmp_path / "individual"
        )


def test_opening_failure_preserves_successful_menu_result(
    tmp_path, monkeypatch, capsys
):
    packet = tmp_path / "packet.pdf"
    operation = generate_workflows.GenerateCommandResult(
        0,
        managed_outputs=(
            generate_workflows.ManagedGeneratedOutput(
                packet, tmp_path / "individual"
            ),
        ),
    )
    monkeypatch.setattr(
        generate_workflows,
        "discover_class_rosters",
        lambda: [
            {"class_id": "class1", "roster_path": tmp_path / "roster.csv"}
        ],
    )
    monkeypatch.setattr(
        generate_workflows,
        "discover_class_assignments",
        lambda _class_id: [
            {
                "assignment_id": "quiz1",
                "assignment_path": tmp_path / "assignment.json",
            }
        ],
    )
    monkeypatch.setattr(generate_workflows, "_run_generate_operation", lambda _args: operation)
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda *_args: (_ for _ in ()).throw(
            generate_workflows.ScoreFormGeneratedOutputOpenError("viewer unavailable")
        ),
    )
    responses = iter(("1", "1", "1", "y", "1", "3"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert generate_workflows.launch_generate_menu() == 0

    output = capsys.readouterr().out
    assert "Error opening generated output" in output
    assert f"Saved path: {packet}" in output
    assert output.count("What would you like to do next?") == 2


def test_failed_packet_open_stays_visible_then_individual_folder_can_open(
    tmp_path, monkeypatch, capsys
):
    packet = tmp_path / "class packet.pdf"
    individual = tmp_path / "individual sheets"
    opened = []
    responses = iter(("1", "2"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda *_args: (_ for _ in ()).throw(
            generate_workflows.ScoreFormGeneratedOutputOpenError("viewer unavailable")
        ),
    )
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda root, path: opened.append((root, Path(path))) or Path(path),
    )

    generate_workflows._offer_assignment_output_actions(
        tmp_path, packet, individual
    )

    output = capsys.readouterr().out
    assert "Error opening generated output: viewer unavailable" in output
    assert f"Saved path: {packet}" in output
    assert output.count("What would you like to do next?") == 2
    assert opened == [(tmp_path, individual)]


def test_failed_packet_open_can_return_without_changing_success(
    tmp_path, monkeypatch, capsys
):
    packet = tmp_path / "packet.pdf"
    responses = iter(("1", "3"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda *_args: (_ for _ in ()).throw(
            generate_workflows.ScoreFormGeneratedOutputOpenError("viewer unavailable")
        ),
    )

    generate_workflows._offer_assignment_output_actions(
        tmp_path, packet, tmp_path / "individual"
    )

    assert capsys.readouterr().out.count("What would you like to do next?") == 2


def test_generic_template_actions_open_file_or_containing_folder(
    tmp_path, monkeypatch
):
    template = tmp_path / "templates with spaces" / "template.pdf"
    opened = []
    responses = iter(("1", "2"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda root, path: opened.append(("file", root, Path(path))) or Path(path),
    )
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda root, path: opened.append(("folder", root, Path(path))) or Path(path),
    )

    generate_workflows._offer_blank_template_actions(tmp_path, template)
    generate_workflows._offer_blank_template_actions(tmp_path, template)

    assert opened == [
        ("file", tmp_path, template),
        ("folder", tmp_path, template.parent),
    ]


def test_blank_template_failure_reprompts_before_opening_folder(
    tmp_path, monkeypatch, capsys
):
    template = tmp_path / "template.pdf"
    opened = []
    responses = iter(("1", "2"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda *_args: (_ for _ in ()).throw(
            generate_workflows.ScoreFormGeneratedOutputOpenError("no viewer")
        ),
    )
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda root, path: opened.append((root, Path(path))) or Path(path),
    )

    generate_workflows._offer_blank_template_actions(tmp_path, template)

    assert capsys.readouterr().out.count("What would you like to do next?") == 2
    assert opened == [(tmp_path, template.parent)]


def test_class_folder_failure_reprompts_before_return(tmp_path, monkeypatch, capsys):
    responses = iter(("1", "2"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda *_args: (_ for _ in ()).throw(
            generate_workflows.ScoreFormGeneratedOutputOpenError("explorer unavailable")
        ),
    )

    generate_workflows._offer_class_output_actions(tmp_path, tmp_path / "work")

    output = capsys.readouterr().out
    assert "Saved path:" in output
    assert output.count("What would you like to do next?") == 2


@pytest.mark.parametrize(
    ("action", "expected_kind"), (("1", "file"), ("2", "folder"))
)
def test_single_assignment_regeneration_offers_exact_paths_with_spaces(
    tmp_path, monkeypatch, capsys, action, expected_kind
):
    packet = tmp_path / "outputs with spaces" / "class packet.pdf"
    individual = tmp_path / "outputs with spaces" / "individual sheets"
    result = generate_workflows.RegenerateSheetsResult(
        "class1",
        "quiz1",
        1,
        1,
        str(packet),
        str(packet.parent),
        individual_templates_dir=str(individual),
    )
    monkeypatch.setattr(
        generate_workflows,
        "discover_class_assignments",
        lambda _class_id: [{"assignment_id": "quiz1"}],
    )
    monkeypatch.setattr(
        generate_workflows, "load_roster", lambda _path: {"students": [{}]}
    )
    monkeypatch.setattr(
        generate_workflows,
        "regenerate_answer_sheets_for_assignment",
        lambda *_args: result,
    )
    monkeypatch.setattr(
        generate_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    opened = []
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda root, path: opened.append(("file", root, Path(path))) or Path(path),
    )
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda root, path: opened.append(("folder", root, Path(path))) or Path(path),
    )
    responses = iter(("1", "1", "REGENERATE", action))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert generate_workflows.launch_regenerate_sheets_menu("class1") == 0

    output = capsys.readouterr().out
    assert "1. Open class packet for printing" in output
    assert "2. Open individual answer sheets folder" in output
    assert "3. Return" in output
    expected_path = packet if expected_kind == "file" else individual
    assert opened == [(expected_kind, tmp_path, expected_path)]


def test_regenerate_all_opens_only_canonical_class_work_folder(
    tmp_path, monkeypatch
):
    result = generate_workflows.RegenerateSheetsResult(
        "class1",
        "quiz1",
        1,
        1,
        str(tmp_path / "packet.pdf"),
        str(tmp_path / "templates"),
    )
    monkeypatch.setattr(
        generate_workflows,
        "discover_class_assignments",
        lambda _class_id: [{"assignment_id": "quiz1"}],
    )
    monkeypatch.setattr(generate_workflows, "load_roster", lambda _path: {"students": [{}]})
    monkeypatch.setattr(
        generate_workflows,
        "regenerate_answer_sheets_for_class",
        lambda _class_id: (result,),
    )
    monkeypatch.setattr(
        generate_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    opened = []
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda root, path: opened.append((root, Path(path))) or Path(path),
    )
    responses = iter(("2", "REGENERATE", "1"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert generate_workflows.launch_regenerate_sheets_menu("class1") == 0

    assert opened == [
        (
            tmp_path,
            tmp_path / "classes" / "class1" / "modules" / "scoreform" / "work",
        )
    ]


def test_noninteractive_generation_and_regeneration_never_prompt_or_open(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        generate_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(generate_workflows, "generate_template", lambda **_kwargs: None)
    monkeypatch.setattr(
        "builtins.input", lambda _prompt="": pytest.fail("unexpected prompt")
    )
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_file",
        lambda *_args: pytest.fail("unexpected file opening"),
    )
    monkeypatch.setattr(
        generate_workflows,
        "open_generated_output_folder",
        lambda *_args: pytest.fail("unexpected folder opening"),
    )
    result = generate_workflows.RegenerateSheetsResult(
        "class1",
        "quiz1",
        1,
        1,
        str(tmp_path / "packet.pdf"),
        str(tmp_path / "templates"),
    )
    monkeypatch.setattr(
        generate_workflows,
        "regenerate_answer_sheets_for_assignment",
        lambda *_args: result,
    )

    assert generate_workflows.run_generate([]) == 0
    assert (
        generate_workflows.run_regenerate_sheets(
            ["--class-id", "class1", "--assignment-id", "quiz1"]
        )
        == 0
    )
