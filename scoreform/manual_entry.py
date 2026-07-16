"""Plain-paper response normalization, scoring, and result construction."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult

MANUAL_ENTRY_SOURCE = "plain_paper_manual_entry"
MANUAL_ENTRY_PAGE = "manual"

_BLANK_ALIASES = {"blank", "bl", "empty"}
_AMBIGUOUS_ALIASES = {"ambiguous", "amb", "double"}
_CANCEL_ALIASES = {"q", "quit", "cancel"}


def normalize_manual_response(
    raw_value: str,
    choices: Sequence[str] = ("A", "B", "C", "D"),
) -> str | None:
    """Normalize a teacher-entered response, or return None when invalid."""
    value = raw_value.strip().lower()
    normalized_choices = {choice.upper() for choice in choices}
    if value.upper() in normalized_choices:
        return value.upper()
    if value in _BLANK_ALIASES:
        return "BLANK"
    if value in _AMBIGUOUS_ALIASES:
        return "AMBIGUOUS"
    return None


def is_manual_entry_cancel(raw_value: str) -> bool:
    """Return whether a response-entry value explicitly cancels the entry."""
    return raw_value.strip().lower() in _CANCEL_ALIASES


def score_manual_responses(
    assignment: Mapping[str, Any],
    responses: Mapping[int, str],
) -> tuple[int, list[dict[str, object]]]:
    """Score normalized responses against an assignment answer key."""
    answers: list[dict[str, object]] = []
    score = 0
    answer_key = assignment["answer_key"]
    for question_number in range(1, int(assignment["question_count"]) + 1):
        response = responses[question_number]
        expected = answer_key.get(question_number, answer_key.get(str(question_number)))
        correct = response in {"A", "B", "C", "D"} and response == expected
        score += int(correct)
        answers.append({
            "Q": question_number,
            "Answer": response,
            "Correct": correct,
        })
    return score, answers


def build_manual_result(
    *,
    class_id: str,
    assignment: Mapping[str, Any],
    student: Mapping[str, str],
    responses: Mapping[int, str],
) -> ScoreFormRoutedResult:
    """Build one immutable plain-paper result for the shared v2 writer."""
    score, answers = score_manual_responses(assignment, responses)
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual", class_id=class_id,
        assignment_id=assignment["assignment_id"], student_id=student["student_id"],
        last_name=student["last_name"], first_name=student["first_name"],
        period=student["period"], page_display=MANUAL_ENTRY_PAGE,
        score=score, total_points=assignment["question_count"],
        answers=tuple(
            ScoredAnswer(
                cast(int, answer["Q"]),
                cast(str, answer["Answer"]),
                cast(bool, answer["Correct"]),
            )
            for answer in answers
        ),
        source_file=MANUAL_ENTRY_SOURCE,
    )


def format_manual_entry_review(
    student: Mapping[str, str],
    assignment: Mapping[str, Any],
    result: ScoreFormRoutedResult,
) -> str:
    """Return the compact confirmation review for one manual result."""
    answers = result.answers
    blanks = sum(answer.selected_answer == "BLANK" for answer in answers)
    ambiguous = sum(answer.selected_answer == "AMBIGUOUS" for answer in answers)
    student_name = f"{student['last_name']}, {student['first_name']}"
    return "\n".join([
        "Review Plain-Paper Result",
        "",
        f"Class: {result.class_id}",
        f"Assignment: {assignment['assignment_id']}",
        f"Student: {student_name}",
        f"Score: {result.score}/{result.total_points}",
        f"Blank responses: {blanks}",
        f"Ambiguous responses: {ambiguous}",
    ])
