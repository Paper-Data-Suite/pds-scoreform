"""Interactive read-only Student Detail workflow for ScoreForm results analysis."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pds_core.menu_navigation import NavigationChoice

from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.results import ScoreFormRoutedResultHistoryRow
from scoreform.results_analysis import (
    ResultsAnalysisError,
    StudentAttemptAnalysis,
    analyze_student_attempt,
    select_recent_display_attempts,
    select_student_attempts,
)
from scoreform.results_standard_display import (
    ResultsStandardsProjection,
    resolve_results_standards_projection,
)
from scoreform.results_viewer import (
    format_student_attempt_detail,
    format_student_standard_detail,
)
from scoreform.workflows import print_menu_header

UiCallback = Callable[[], None]
InputCallback = Callable[[str], str]


def _select_student(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    *,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback,
) -> str | None:
    selections = select_recent_display_attempts(rows)
    while True:
        clear_screen_fn()
        print_menu_header("Student Detail")
        print("Select a student:")
        print()
        for index, selection in enumerate(selections, start=1):
            result = selection.row.result
            name = ", ".join(
                value for value in (result.last_name, result.first_name) if value
            )
            print(
                f"{index}. {result.student_id} - {name or '(name unavailable)'} "
                f"({selection.attempt_count} attempt"
                f"{'' if selection.attempt_count == 1 else 's'})"
            )
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select student: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(selections):
                return selections[index - 1].student_id

        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        input_fn("Press Enter to continue...")


def _select_attempt(
    attempts: Sequence[ScoreFormRoutedResultHistoryRow],
    *,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback,
) -> ScoreFormRoutedResultHistoryRow | None:
    if not attempts:
        raise ResultsAnalysisError("Selected student has no preserved attempts.")
    if len(attempts) == 1:
        return attempts[0]

    # select_student_attempts() already applies the shared timestamp-aware
    # chronological ordering from the analysis layer.
    recent = attempts[-1]

    while True:
        clear_screen_fn()
        print_menu_header("Select Student Attempt")
        print("Every preserved scored attempt remains independently viewable.")
        print("Press Enter to use the most recent display attempt.")
        print()
        for index, row in enumerate(attempts, start=1):
            result = row.result
            marker = "  [most recent display]" if row is recent else ""
            print(
                f"{index}. Attempt {row.attempt_number} - "
                f"{result.score}/{result.total_points} - {row.scan_timestamp}{marker}"
            )
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select attempt (Enter = most recent): ").strip()
        if choice == "":
            return recent
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(attempts):
                return attempts[index - 1]

        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        input_fn("Press Enter to continue...")


def _select_standard(
    analysis: StudentAttemptAnalysis,
    *,
    standard_display: ResultsStandardsProjection,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback,
) -> str | None:
    if not analysis.standards:
        return None

    while True:
        clear_screen_fn()
        print_menu_header("Student Standard Detail")
        print("Standards basis: current assignment alignment")
        print()
        for index, standard in enumerate(analysis.standards, start=1):
            percent = (
                "—"
                if standard.percent_correct is None
                else f"{standard.percent_correct}%"
            )
            print(
                f"{index}. {standard_display.label_for(standard.standard_id)} - "
                f"{standard.correct}/{standard.responses} ({percent})"
            )
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select Standard: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(analysis.standards):
                return analysis.standards[index - 1].standard_id

        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        input_fn("Press Enter to continue...")


def launch_student_detail_menu(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback = input,
    workspace_root: str | Path | None = None,
) -> int:
    """Inspect one student's exact preserved result attempts without writing state."""
    student_id = _select_student(
        rows,
        clear_screen_fn=clear_screen_fn,
        input_fn=input_fn,
    )
    if student_id is None:
        return 0

    while True:
        attempts = select_student_attempts(rows, student_id)
        selected = _select_attempt(
            attempts,
            clear_screen_fn=clear_screen_fn,
            input_fn=input_fn,
        )
        if selected is None:
            return 0

        analysis = analyze_student_attempt(
            selected,
            assignment,
            class_id=class_id,
            attempt_count=len(attempts),
        )
        standard_display = resolve_results_standards_projection(
            (item.standard_id for item in analysis.standards),
            workspace_root=workspace_root,
        )

        while True:
            clear_screen_fn()
            print(
                format_student_attempt_detail(
                    analysis,
                    standard_display=standard_display,
                )
            )
            print()
            print("1. View Standard Detail")
            if len(attempts) > 1:
                print("2. Choose Another Attempt")
                print("3. Choose Another Student")
            else:
                print("2. Choose Another Student")
            print_scoreform_navigation_options()
            print()

            choice = input_fn("Select an option: ").strip()
            navigation = parse_scoreform_navigation(choice)
            if navigation is NavigationChoice.BACK:
                return 0

            if choice == "1":
                if not analysis.standards:
                    print("No Standards are aligned to this assignment.")
                    input_fn("Press Enter to continue...")
                    continue
                standard_id = _select_standard(
                    analysis,
                    standard_display=standard_display,
                    clear_screen_fn=clear_screen_fn,
                    input_fn=input_fn,
                )
                if standard_id is None:
                    continue
                clear_screen_fn()
                print(
                    format_student_standard_detail(
                        analysis,
                        standard_id,
                        standard_display=standard_display,
                    )
                )
                print()
                input_fn("Press Enter to return to Student Detail...")
                continue

            if len(attempts) > 1 and choice == "2":
                break
            if (
                len(attempts) > 1
                and choice == "3"
                or len(attempts) == 1
                and choice == "2"
            ):
                student_id = _select_student(
                    rows,
                    clear_screen_fn=clear_screen_fn,
                    input_fn=input_fn,
                )
                if student_id is None:
                    return 0
                break

            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()
            input_fn("Press Enter to continue...")
def _select_question(
    analysis,
    *,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback,
) -> int | None:
    from scoreform.results_viewer import format_question_analysis_table

    while True:
        clear_screen_fn()
        print(format_question_analysis_table(analysis))
        print()
        print("Select a question for response distribution.")
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Question number: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return None
        if choice.isdigit():
            question_number = int(choice)
            if 1 <= question_number <= len(analysis.questions):
                return question_number

        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        input_fn("Press Enter to continue...")


def launch_question_analysis_menu(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback = input,
) -> int:
    """Inspect class-level item analysis using recent display attempts."""
    from scoreform.results_analysis import analyze_class_results
    from scoreform.results_viewer import format_question_response_distribution

    analysis = analyze_class_results(rows, assignment, class_id=class_id)

    while True:
        question_number = _select_question(
            analysis,
            clear_screen_fn=clear_screen_fn,
            input_fn=input_fn,
        )
        if question_number is None:
            return 0

        clear_screen_fn()
        print(format_question_response_distribution(analysis, question_number))
        print()
        input_fn("Press Enter to return to Question Analysis...")


def _select_class_standard(
    analysis,
    *,
    standard_display: ResultsStandardsProjection,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback,
) -> str | None:
    from scoreform.results_viewer import format_class_standards_analysis

    if not analysis.standards:
        clear_screen_fn()
        print(
            format_class_standards_analysis(
                analysis,
                standard_display=standard_display,
            )
        )
        print()
        input_fn("Press Enter to return...")
        return None

    while True:
        clear_screen_fn()
        print(
            format_class_standards_analysis(
                analysis,
                standard_display=standard_display,
            )
        )
        print()
        print("Select a Standard for contributing-question detail.")
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select Standard: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(analysis.standards):
                return analysis.standards[index - 1].standard_id

        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        input_fn("Press Enter to continue...")


def launch_class_standards_analysis_menu(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
    clear_screen_fn: UiCallback,
    input_fn: InputCallback = input,
    workspace_root: str | Path | None = None,
) -> int:
    """Inspect descriptive class Standard counts and contributing questions."""
    from scoreform.results_analysis import analyze_class_results
    from scoreform.results_viewer import format_class_standard_detail

    analysis = analyze_class_results(rows, assignment, class_id=class_id)
    standard_display = resolve_results_standards_projection(
        (item.standard_id for item in analysis.standards),
        workspace_root=workspace_root,
    )

    while True:
        standard_id = _select_class_standard(
            analysis,
            standard_display=standard_display,
            clear_screen_fn=clear_screen_fn,
            input_fn=input_fn,
        )
        if standard_id is None:
            return 0

        clear_screen_fn()
        print(
            format_class_standard_detail(
                analysis,
                standard_id,
                standard_display=standard_display,
            )
        )
        print()
        input_fn("Press Enter to return to Standards Analysis...")
