"""Generate answer-sheet command and menu workflows."""

import os
from dataclasses import dataclass
from pathlib import Path

from pds_core.routes import class_roster_path

from scoreform import workspace
from scoreform.answer_sheet_generation import (
    AnswerSheetGenerationPreflightError,
    AnswerSheetGenerationResult,
    generate_managed_answer_sheets,
)
from scoreform.answer_sheet_records import generate_generation_id
from scoreform.assignment import load_assignment
from scoreform.config import LOCAL_TEMPLATE_PDF, LOCAL_TEMPLATE_PNG
from scoreform.folders import setup_assignment_folder
from scoreform.generated_output_opening import (
    ScoreFormGeneratedOutputOpenError,
    open_generated_output_file,
    open_generated_output_folder,
)
from scoreform.layouts import get_layout
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.paging import page_count_for_question_count
from scoreform.roster import load_roster
from scoreform.templates import generate_template, student_pdf_filename
from scoreform.validation import is_safe_identifier
from scoreform.work_paths import scoreform_work_collection_dir, scoreform_work_paths
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
)


@dataclass(frozen=True)
class RegenerateSheetsResult:
    """Summary of regenerated print artifacts for one managed assignment."""

    class_id: str
    assignment_id: str
    student_count: int
    individual_count: int
    class_packet_path: str
    templates_dir: str
    pages_per_student: int = 1
    stale_extra_count: int = 0
    stale_extra_examples: tuple[str, ...] = ()
    generation_result: AnswerSheetGenerationResult | None = None
    individual_templates_dir: str = ""


@dataclass(frozen=True, slots=True)
class ManagedGeneratedOutput:
    """Structured output paths from one successful managed generation."""

    class_packet_path: Path
    individual_templates_dir: Path


@dataclass(frozen=True, slots=True)
class GenerateCommandResult:
    """Internal structured result while the public command retains an int."""

    exit_code: int
    managed_outputs: tuple[ManagedGeneratedOutput, ...] = ()
    blank_template_path: Path | None = None


def launch_multi_class_generation_menu():
    """Lazy adapter to the #186 teacher-facing multi-target workflow."""
    from scoreform.multi_class_generation_ui import (
        launch_multi_class_generation_menu as launch,
    )

    return launch()


class ManagedAnswerSheetGenerationFailure(RuntimeError):
    """Carry structured generation state through regeneration entry points."""

    def __init__(self, generation_result: AnswerSheetGenerationResult):
        self.generation_result = generation_result
        super().__init__("\n".join(_generation_failure_lines(generation_result)))


def _generation_failure_lines(
    result: AnswerSheetGenerationResult,
    *,
    earlier_installed: int = 0,
    earlier_clean: int = 0,
    earlier_partial: int = 0,
) -> tuple[str, ...]:
    failed = result.artifacts[-1]
    lines: list[str] = []
    if failed.partial_success:
        lines.extend(
            (
                "The new PDF was installed and its new issuances are issued, but "
                "one or more previous issuances could not be superseded.",
                f"Output: {failed.output_path}",
            )
        )
    else:
        lines.append(
            f"Generation failed at {failed.failure_stage} for "
            f"{failed.output_path}: {failed.error}"
        )
    installed = earlier_installed + result.installed_artifact_count
    clean = earlier_clean + result.clean_success_count
    partial = earlier_partial + result.partial_artifact_count
    completed_earlier = installed - (1 if failed.installed else 0)
    lines.extend(
        (
            f"Installed artifacts: {installed}",
            f"Clean-success artifacts: {clean}",
            f"Partial artifacts: {partial}",
            f"Completed earlier artifacts: {completed_earlier}",
            f"Routes planned/created/verified: {failed.planned_route_count}/"
            f"{failed.created_route_count}/{failed.verified_route_count}",
        )
    )
    if failed.failed_predecessor_ids:
        lines.append(
            "Predecessors not superseded: "
            + ", ".join(failed.failed_predecessor_ids)
        )
    if failed.partial_success and failed.error:
        lines.append(f"Lifecycle finalization error: {failed.error}")
    lines.extend(f"Warning: {warning}" for warning in failed.warnings)
    return tuple(lines)


def regenerate_answer_sheets_for_assignment(
    class_id,
    assignment_id,
    workspace_root=None,
    *,
    generation_id=None,
    used_artifact_ids=None,
    used_issuance_ids=None,
    used_page_ids=None,
    used_route_ids=None,
):
    """Regenerate one assignment from its current managed roster and assignment."""
    if not is_safe_identifier(class_id):
        raise ValueError(f"Unsafe class_id: {class_id!r}")
    if not is_safe_identifier(assignment_id):
        raise ValueError(f"Unsafe assignment_id: {assignment_id!r}")

    root = Path(workspace_root or workspace.get_scoreform_workspace_root())
    paths = scoreform_work_paths(root, class_id, assignment_id)
    roster_path = paths.roster_path
    assignment_path = paths.assignment_path
    if not roster_path.is_file():
        raise FileNotFoundError(f"Managed roster not found for class '{class_id}': {roster_path}")
    if not assignment_path.is_file():
        raise FileNotFoundError(
            f"Managed assignment '{assignment_id}' not found for class '{class_id}': {assignment_path}"
        )

    roster = load_roster(roster_path)
    if roster is None:
        raise ValueError(f"Managed roster is invalid for class '{class_id}'.")
    assignment = load_assignment(assignment_path)
    if assignment is None:
        raise ValueError(f"Managed assignment '{assignment_id}' is invalid.")
    if roster.get("class_id") != class_id:
        raise ValueError(
            f"Managed roster class_id '{roster.get('class_id')}' does not match '{class_id}'."
        )
    if assignment.get("assignment_id") != assignment_id:
        raise ValueError(
            "Managed assignment identifier does not match its assignment folder."
        )

    templates_dir = paths.templates_dir
    individual_dir = paths.individual_templates_dir
    for directory in (templates_dir, individual_dir):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError(f"Managed template path is not a directory: {directory}")
        directory.mkdir(parents=True, exist_ok=True)
    expected_names = {student_pdf_filename(student) for student in roster["students"]}
    existing_names = {
        path.name for path in individual_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    }

    packet_path = paths.class_packet_path
    generation_result = generate_managed_answer_sheets(
        root,
        paths.work_ref,
        assignment,
        roster,
        individual_dir=individual_dir,
        class_packet_path=packet_path,
        student_filename=student_pdf_filename,
        generation_id=generation_id,
        used_artifact_ids=used_artifact_ids,
        used_issuance_ids=used_issuance_ids,
        used_page_ids=used_page_ids,
        used_route_ids=used_route_ids,
    )
    if not generation_result.success:
        raise ManagedAnswerSheetGenerationFailure(generation_result)

    stale = sorted(existing_names - expected_names, key=str.lower)
    return RegenerateSheetsResult(
        class_id=class_id,
        assignment_id=assignment_id,
        student_count=len(roster["students"]),
        individual_count=len(roster["students"]),
        class_packet_path=os.fspath(packet_path),
        templates_dir=os.fspath(templates_dir),
        individual_templates_dir=os.fspath(individual_dir),
        pages_per_student=page_count_for_question_count(
            assignment["question_count"], get_layout(assignment["layout_id"])
        ),
        stale_extra_count=len(stale),
        stale_extra_examples=tuple(stale[:3]),
        generation_result=generation_result,
    )


def regenerate_answer_sheets_for_class(class_id, workspace_root=None):
    """Regenerate every managed assignment while preserving earlier successes."""
    if not is_safe_identifier(class_id):
        raise ValueError(f"Unsafe class_id: {class_id!r}")
    root = Path(workspace_root or workspace.get_scoreform_workspace_root())
    assignments = discover_class_assignments(class_id, workspace_root=root)
    roster_path = class_roster_path(root, class_id)
    if not roster_path.is_file():
        raise FileNotFoundError(f"Managed roster not found for class '{class_id}'.")
    assignment_ids = [record["assignment_id"] for record in assignments]
    if not assignment_ids:
        raise FileNotFoundError(f"No managed assignments found for class '{class_id}'.")
    generation_id = generate_generation_id()
    results = []
    for assignment_id in assignment_ids:
        try:
            results.append(
                regenerate_answer_sheets_for_assignment(
                    class_id, assignment_id, root, generation_id=generation_id
                )
            )
        except ManagedAnswerSheetGenerationFailure as error:
            previous_generation_results = tuple(
                item.generation_result
                for item in results
                if item.generation_result is not None
            )
            lines = _generation_failure_lines(
                error.generation_result,
                earlier_installed=sum(
                    item.installed_artifact_count
                    for item in previous_generation_results
                ),
                earlier_clean=sum(
                    item.clean_success_count for item in previous_generation_results
                ),
                earlier_partial=sum(
                    item.partial_artifact_count
                    for item in previous_generation_results
                ),
            )
            raise RuntimeError(
                f"Regeneration failed for assignment '{assignment_id}' after "
                f"{len(results)} assignment(s) completed; completed outputs were "
                "preserved.\n" + "\n".join(lines)
            ) from error
        except Exception as error:
            raise RuntimeError(
                f"Regeneration failed for assignment '{assignment_id}' after "
                f"{len(results)} assignment(s) completed; completed outputs were "
                f"preserved: {error}"
            ) from error
    return tuple(results)


def _print_stale_note(result, *, include_examples=False):
    if not result.stale_extra_count:
        return
    print()
    print(
        f"Note: {result.stale_extra_count} older individual PDFs were not changed. "
        "Review the individual templates folder before printing individual sheets."
    )
    if include_examples and result.stale_extra_examples:
        print("Examples: " + ", ".join(result.stale_extra_examples))


def _open_output_or_report(
    operation,
    workspace_root: Path,
    output_path: str | os.PathLike[str],
) -> bool:
    try:
        opened = operation(workspace_root, output_path)
    except ScoreFormGeneratedOutputOpenError as error:
        print(f"Error opening generated output: {error}")
        print(f"Saved path: {output_path}")
        return False
    print(f"Opened: {opened}")
    return True


def _offer_assignment_output_actions(
    workspace_root: Path,
    class_packet_path: str | os.PathLike[str],
    individual_templates_dir: str | os.PathLike[str],
) -> None:
    while True:
        print("\nWhat would you like to do next?\n")
        print("1. Open class packet for printing")
        print("2. Open individual answer sheets folder")
        print("3. Return")
        selection = input("Select an option: ").strip()
        if not selection or selection == "3":
            return
        if parse_scoreform_navigation(selection) is not None:
            return
        if selection == "1":
            if _open_output_or_report(
                open_generated_output_file, workspace_root, class_packet_path
            ):
                return
            continue
        if selection == "2":
            if _open_output_or_report(
                open_generated_output_folder,
                workspace_root,
                individual_templates_dir,
            ):
                return
            continue
        print(f"Invalid selection: {selection}.")
        print_invalid_navigation()


def _offer_class_output_actions(workspace_root: Path, class_work_dir: Path) -> None:
    while True:
        print("\nWhat would you like to do next?\n")
        print("1. Open class ScoreForm work folder")
        print("2. Return")
        selection = input("Select an option: ").strip()
        if not selection or selection == "2":
            return
        if parse_scoreform_navigation(selection) is not None:
            return
        if selection == "1":
            if _open_output_or_report(
                open_generated_output_folder, workspace_root, class_work_dir
            ):
                return
            continue
        print(f"Invalid selection: {selection}.")
        print_invalid_navigation()


def _offer_blank_template_actions(
    workspace_root: Path, template_path: Path
) -> None:
    while True:
        print("\nWhat would you like to do next?\n")
        print("1. Open generated template")
        print("2. Open containing folder")
        print("3. Return")
        selection = input("Select an option: ").strip()
        if not selection or selection == "3":
            return
        if parse_scoreform_navigation(selection) is not None:
            return
        if selection == "1":
            if _open_output_or_report(
                open_generated_output_file, workspace_root, template_path
            ):
                return
            continue
        if selection == "2":
            if _open_output_or_report(
                open_generated_output_folder, workspace_root, template_path.parent
            ):
                return
            continue
        print(f"Invalid selection: {selection}.")
        print_invalid_navigation()


def run_regenerate_sheets(args):
    """Run the non-interactive managed answer-sheet regeneration command."""
    usage = (
        "Usage: scoreform regenerate-sheets --class-id <class_id> "
        "(--assignment-id <assignment_id> | --all-assignments)"
    )
    if not args or args in (["help"], ["--help"], ["-h"]):
        print(usage)
        print("Regenerate print artifacts from the current managed roster and assignment files.")
        return 0
    class_id = None
    assignment_id = None
    all_assignments = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"--class-id", "--assignment-id"}:
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                print(f"Error: {arg} requires a value.\n{usage}")
                return 1
            if arg == "--class-id":
                if class_id is not None:
                    print(f"Error: {arg} may be specified only once.\n{usage}")
                    return 1
                class_id = args[index + 1]
            else:
                if assignment_id is not None:
                    print(f"Error: {arg} may be specified only once.\n{usage}")
                    return 1
                assignment_id = args[index + 1]
            index += 2
            continue
        if arg == "--all-assignments":
            if all_assignments:
                print(f"Error: {arg} may be specified only once.\n{usage}")
                return 1
            all_assignments = True
            index += 1
            continue
        print(f"Error: Unknown option: {arg}\n{usage}")
        return 1

    if not class_id:
        print(f"Error: --class-id is required.\n{usage}")
        return 1
    if not is_safe_identifier(class_id):
        print(f"Error: class_id is unsafe: '{class_id}'.")
        return 1
    if (assignment_id is None) == (not all_assignments):
        print(f"Error: Choose exactly one of --assignment-id or --all-assignments.\n{usage}")
        return 1
    if assignment_id is not None and not is_safe_identifier(assignment_id):
        print(f"Error: assignment_id is unsafe: '{assignment_id}'.")
        return 1

    try:
        if assignment_id is not None:
            result = regenerate_answer_sheets_for_assignment(class_id, assignment_id)
            print("Regenerated answer sheets.\n")
            print(f"Class: {class_id}")
            print(f"Assignment: {assignment_id}")
            print(f"Students: {result.student_count}")
            print(f"Pages per student: {result.pages_per_student}")
            print(f"Individual sheets: {result.individual_count}")
            print(f"Class packet: {result.class_packet_path}")
            _print_stale_note(result, include_examples=True)
        else:
            results = regenerate_answer_sheets_for_class(class_id)
            print("Regenerated answer sheets.\n")
            print(f"Class: {class_id}")
            print(f"Assignments updated: {len(results)}")
            print(f"Students in current roster: {results[0].student_count}")
            stale_count = sum(result.stale_extra_count for result in results)
            if stale_count:
                print()
                print(f"Note: {stale_count} older individual PDFs were not changed.")
                print("Review the individual templates folders before printing individual sheets.")
    except (
        AnswerSheetGenerationPreflightError,
        FileNotFoundError,
        ValueError,
        RuntimeError,
    ) as error:
        print(f"Error: {error}")
        return 1
    return 0


def launch_regenerate_sheets_menu(preselected_class_id=None):
    """Run the compact teacher-facing managed regeneration workflow."""
    clear_screen()
    print_menu_header("Update Generated Answer Sheets")
    if preselected_class_id is None:
        classes = discover_class_rosters()
        if not classes:
            print("No class rosters found.")
            return 1
        print("Select class:")
        for index, record in enumerate(classes, start=1):
            print(f"{index}. {record['class_id']}")
        print_scoreform_navigation_options()
        try:
            selection = input("Select class: ")
            if parse_scoreform_navigation(selection) is not None:
                return 0
            class_id = parse_single_selection(selection, classes, "class")["class_id"]
        except ValueError as error:
            print(f"Error: {error}")
            return 1
    else:
        class_id = preselected_class_id

    assignments = discover_class_assignments(class_id)
    if not assignments:
        print(f"No assignments found for class '{class_id}' yet.")
        return 0
    roster_path = Path(workspace.get_scoreform_workspace_root()) / "classes" / class_id / "roster.csv"
    roster = load_roster(roster_path)
    if roster is None:
        return 1

    clear_screen()
    print_menu_header("Update Generated Answer Sheets")
    print(f"Class: {class_id}")
    print()
    print("1. Update sheets for one assignment")
    print("2. Update sheets for all assignments")
    print("3. Not now")
    mode = input("Select an option: ").strip()
    if mode == "3" or parse_scoreform_navigation(mode) is not None:
        print("Answer sheets were not changed.")
        return 0
    if mode not in {"1", "2"}:
        print(f"Invalid selection: {mode}.")
        return 1

    if mode == "1":
        clear_screen()
        print_menu_header("Update Generated Answer Sheets")
        print(f"Class: {class_id}\n")
        print("Select assignment:")
        for index, record in enumerate(assignments, start=1):
            print(f"{index}. {record['assignment_id']}")
        print_scoreform_navigation_options()
        try:
            selection = input("Select assignment: ")
            if parse_scoreform_navigation(selection) is not None:
                return 0
            assignment_id = parse_single_selection(
                selection, assignments, "assignment"
            )["assignment_id"]
        except ValueError as error:
            print(f"Error: {error}")
            return 1
        clear_screen()
        print_menu_header("Regenerate Answer Sheets?")
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment_id}")
        print(f"Students: {len(roster['students'])}\n")
        if input("Type REGENERATE to continue: ").strip() != "REGENERATE":
            print("Cancelled: regeneration not confirmed.")
            return 0
        try:
            result = regenerate_answer_sheets_for_assignment(class_id, assignment_id)
        except (
            AnswerSheetGenerationPreflightError,
            FileNotFoundError,
            ValueError,
            RuntimeError,
        ) as error:
            print(f"Error: {error}")
            return 1
        clear_screen()
        print_menu_header("Answer Sheets Updated")
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment_id}")
        print(f"Students: {result.student_count}")
        print(f"Pages per student: {result.pages_per_student}")
        print(f"Class packet: {result.class_packet_path}")
        if result.stale_extra_count:
            print("\nNote: Older individual PDFs remain in the templates folder.")
            print("Review that folder before printing individual sheets.")
        individual_dir = result.individual_templates_dir or os.fspath(
            Path(result.templates_dir) / "individual"
        )
        _offer_assignment_output_actions(
            Path(workspace.get_scoreform_workspace_root()),
            result.class_packet_path,
            individual_dir,
        )
        return 0

    clear_screen()
    print_menu_header("Regenerate Answer Sheets for All Assignments?")
    print(f"Class: {class_id}")
    print(f"Assignments: {len(assignments)}")
    print(f"Students: {len(roster['students'])}\n")
    if input("Type REGENERATE to continue: ").strip() != "REGENERATE":
        print("Cancelled: regeneration not confirmed.")
        return 0
    try:
        results = regenerate_answer_sheets_for_class(class_id)
    except (
        AnswerSheetGenerationPreflightError,
        FileNotFoundError,
        ValueError,
        RuntimeError,
    ) as error:
        print(f"Error: {error}")
        return 1
    clear_screen()
    print_menu_header("Answer Sheets Updated")
    print(f"Class: {class_id}")
    print(f"Assignments updated: {len(results)}")
    print(f"Students: {results[0].student_count}")
    if any(result.stale_extra_count for result in results):
        print("\nNote: Older individual PDFs remain in the templates folders.")
        print("Review those folders before printing individual sheets.")
    root = Path(workspace.get_scoreform_workspace_root())
    _offer_class_output_actions(
        root,
        scoreform_work_collection_dir(root, class_id),
    )
    return 0


def _run_generate_operation(args) -> GenerateCommandResult:
    """Generate outputs and return their paths without adding menu prompts."""
    if not args:
        root = Path(workspace.get_scoreform_workspace_root())
        template_path = root / LOCAL_TEMPLATE_PDF
        generate_template(
            pdf_filename=os.fspath(template_path),
            png_filename=os.fspath(root / LOCAL_TEMPLATE_PNG),
        )
        return GenerateCommandResult(0, blank_template_path=template_path)

    assignment_file = args[0]
    if "--rosters" not in args[1:]:
        print("Error: Missing --rosters.\nUsage: scoreform generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
        return GenerateCommandResult(1)

    rosters_index = args.index("--rosters")
    roster_files = args[rosters_index + 1 :]

    if not roster_files:
        print("Error: --rosters provided but no roster files specified.")
        print("Usage: scoreform generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
        return GenerateCommandResult(1)

    assignment = load_assignment(assignment_file)
    if assignment is None:
        return GenerateCommandResult(1)

    command_generation_id = generate_generation_id()
    installed_artifacts = 0
    clean_artifacts = 0
    partial_artifacts = 0
    managed_outputs = []
    for roster_path in roster_files:
        roster = load_roster(roster_path)
        if roster is None:
            print(f"Error: Failed to load/validate roster: {roster_path}")
            return GenerateCommandResult(1)

        setup_paths = setup_assignment_folder(roster, assignment)
        if setup_paths is None:
            print(f"Error: Failed to setup assignment folder for roster: {roster_path}")
            return GenerateCommandResult(1)

        print("--- Setup Summary ---")
        print(f"Class: {roster.get('class_id')}")
        print(f"  Work root: {setup_paths['work_root']}")
        print(f"  Roster path: {setup_paths['roster_path']}")
        print(f"  Assignment path: {setup_paths['assignment_path']}")

        paths = setup_paths["paths"]
        managed_assignment = load_assignment(paths.assignment_path)
        managed_roster = load_roster(paths.roster_path)
        if managed_assignment is None or managed_roster is None:
            print("Error: Canonical managed assignment or roster could not be reloaded.")
            return GenerateCommandResult(1)

        try:
            generation_result = generate_managed_answer_sheets(
                workspace.get_scoreform_workspace_root(),
                paths.work_ref,
                managed_assignment,
                managed_roster,
                individual_dir=paths.individual_templates_dir,
                class_packet_path=paths.class_packet_path,
                student_filename=student_pdf_filename,
                generation_id=command_generation_id,
            )
        except AnswerSheetGenerationPreflightError as error:
            print(f"Error: Managed answer-sheet preflight failed: {error}")
            for note in getattr(error, "__notes__", ()):
                print(f"Warning: {note}")
            return GenerateCommandResult(1)
        except Exception as error:
            print(f"Error: Managed answer-sheet orchestration failed: {error}")
            return GenerateCommandResult(1)
        if not generation_result.success:
            for index, line in enumerate(
                _generation_failure_lines(
                    generation_result,
                    earlier_installed=installed_artifacts,
                    earlier_clean=clean_artifacts,
                    earlier_partial=partial_artifacts,
                )
            ):
                print(("Error: " if index == 0 else "") + line)
            return GenerateCommandResult(1)

        installed_artifacts += generation_result.installed_artifact_count
        clean_artifacts += generation_result.clean_success_count
        partial_artifacts += generation_result.partial_artifact_count

        print(f"Generated {len(managed_roster['students'])} individual student PDFs in:")
        print(
            "Pages per student: "
            f"{page_count_for_question_count(managed_assignment['question_count'], get_layout(managed_assignment['layout_id']))}"
        )
        print(paths.individual_templates_dir)
        print("Generated class packet PDF:")
        print(paths.class_packet_path)
        print(
            f"Verified PDS2 routes: {generation_result.installed_route_count}; "
            f"physical pages: {generation_result.physical_page_count}"
        )
        managed_outputs.append(
            ManagedGeneratedOutput(
                class_packet_path=Path(paths.class_packet_path),
                individual_templates_dir=Path(paths.individual_templates_dir),
            )
        )

    return GenerateCommandResult(0, managed_outputs=tuple(managed_outputs))


def run_generate(args):
    """Generate outputs noninteractively and preserve the public integer result."""
    return _run_generate_operation(args).exit_code


def launch_generate_menu(context_session=None):
    """Teacher-centered generate submenu for interactive menu use."""
    try:
        while True:
            clear_screen()
            print_menu_header("Generate Answer Sheets")
            print("1. Generate answer sheets for an existing class assignment")
            print("2. Generate a generic blank template")
            print("3. Plan generation for multiple classes/assignments")
            print_scoreform_navigation_options()
            print()

            choice = input("Select an option: ").strip()
            print()

            navigation = parse_scoreform_navigation(choice)
            if navigation is not None:
                return 0

            if choice == "1":
                if context_session is not None:
                    from scoreform.menu_assignment_context import (
                        select_assignment_for_workflow,
                    )

                    assignment_record = select_assignment_for_workflow(
                        context_session,
                        clear_screen_fn=clear_screen,
                        offer_switch=True,
                        workflow_title="Generate Answer Sheets",
                    )
                    if assignment_record is None:
                        continue
                    class_id = assignment_record["class_id"]
                    roster_path = assignment_record["roster_path"]
                else:
                    clear_screen()
                    print_menu_header("Generate Answer Sheets")
                    available_classes = discover_class_rosters()
                    if not available_classes:
                        print("No class rosters found. Create a class roster first from the Roster Management menu.")
                        pause_for_user()
                        return 1

                    print("Available classes:")
                    for index, class_record in enumerate(available_classes, start=1):
                        print(f"{index}. {class_record['class_id']}")
                    print_scoreform_navigation_options()
                    print()

                    try:
                        selection = input("Select class: ")
                        if parse_scoreform_navigation(selection) is not None:
                            continue
                        class_record = parse_single_selection(
                            selection,
                            available_classes,
                            "class",
                        )
                    except ValueError as e:
                        print(f"Error: {e}")
                        pause_for_user()
                        return 1

                    class_id = class_record["class_id"]
                    roster_path = class_record["roster_path"]
                    available_assignments = discover_class_assignments(class_id)
                    if not available_assignments:
                        print(f"No assignments found for class '{class_id}'. Create an assignment first from the Assignment Management menu.")
                        pause_for_user()
                        return 1

                    clear_screen()
                    print_menu_header("Generate Answer Sheets")
                    print(f"Class: {class_id}")
                    print()
                    print("Available assignments:")
                    for index, assignment_record in enumerate(available_assignments, start=1):
                        print(f"{index}. {assignment_record['assignment_id']}")
                    print_scoreform_navigation_options()
                    print()

                    try:
                        selection = input("Select assignment: ")
                        if parse_scoreform_navigation(selection) is not None:
                            continue
                        assignment_record = parse_single_selection(
                            selection,
                            available_assignments,
                            "assignment",
                        )
                    except ValueError as e:
                        print(f"Error: {e}")
                        pause_for_user()
                        return 1

                assignment_id = assignment_record["assignment_id"]
                clear_screen()
                print_menu_header("Generate Answer Sheets")
                print("Generate answer sheets for:")
                print(f"Class: {class_id}")
                print(f"Assignment: {assignment_id}")
                print()

                response = input("Generate answer sheets now? (Y/n): ").strip().lower()
                if response in ("n", "no"):
                    print("Cancelled: Answer sheet generation not confirmed.")
                    pause_for_user()
                    return 1

                operation = _run_generate_operation(
                    [
                        assignment_record["assignment_path"],
                        "--rosters",
                        roster_path,
                    ]
                )
                if operation.exit_code == 0 and operation.managed_outputs:
                    output = operation.managed_outputs[0]
                    _offer_assignment_output_actions(
                        Path(workspace.get_scoreform_workspace_root()),
                        output.class_packet_path,
                        output.individual_templates_dir,
                    )
                return operation.exit_code

            elif choice == "2":
                clear_screen()
                print_menu_header("Generate a Generic Blank Template")
                operation = _run_generate_operation([])
                if operation.exit_code == 0 and operation.blank_template_path:
                    _offer_blank_template_actions(
                        Path(workspace.get_scoreform_workspace_root()),
                        operation.blank_template_path,
                    )
                return operation.exit_code

            elif choice == "3":
                return launch_multi_class_generation_menu()

            else:
                print(f"Invalid selection: {choice}.")
                print_invalid_navigation()
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting generate menu.")
        return 0
