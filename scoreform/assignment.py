import json
import os

from scoreform.config import MAX_QUESTION_COUNT
from scoreform.validation import validate_identifier

VALID_ANSWER_CHOICES = {"A", "B", "C", "D"}


def _normalize_question_number(key, question_count, field_name):
    if isinstance(key, str) and key.isdigit():
        q_num = int(key)
    elif isinstance(key, int):
        q_num = key
    else:
        print(
            f"Error: Invalid question number in {field_name}: {key!r}. "
            f"Question numbers must be 1 through {question_count}."
        )
        return None

    if q_num < 1 or q_num > question_count:
        print(
            f"Error: Invalid question number '{q_num}' in {field_name}. "
            f"Question numbers must be 1 through {question_count}."
        )
        return None

    return q_num


def _normalize_answer_choice(value, q_num, valid_choices):
    if not isinstance(value, str):
        print(
            f"Error: Invalid answer for question {q_num}: {value!r}. "
            "Answers must be A, B, C, or D."
        )
        return None

    answer = value.strip().upper()
    if answer not in valid_choices:
        print(
            f"Error: Invalid answer for question {q_num}: {value!r}. "
            "Answers must be A, B, C, or D."
        )
        return None

    return answer


def _normalize_answer_key(
    answer_key,
    *,
    question_count=None,
    valid_choices=None,
    max_questions=MAX_QUESTION_COUNT,
    field_name="answer_key",
):
    if valid_choices is None:
        valid_choices = VALID_ANSWER_CHOICES

    if not isinstance(answer_key, dict):
        print(f"Error: '{field_name}' must be a JSON object.")
        return None

    if question_count is not None and len(answer_key) != question_count:
        print(
            f"Error: '{field_name}' must contain exactly {question_count} entries."
        )
        return None

    question_limit = question_count if question_count is not None else max_questions
    normalized_answer_key = {}
    for key, value in answer_key.items():
        q_num = _normalize_question_number(key, question_limit, field_name)
        if q_num is None:
            return None

        if q_num in normalized_answer_key:
            print(f"Error: Duplicate question number '{q_num}' in {field_name}.")
            return None

        answer = _normalize_answer_choice(value, q_num, valid_choices)
        if answer is None:
            return None

        normalized_answer_key[q_num] = answer

    if not normalized_answer_key:
        print("Error: Answer key must contain at least one question.")
        return None

    expected_max_question = question_count
    if expected_max_question is None:
        expected_max_question = max(normalized_answer_key.keys())

    expected_questions = set(range(1, expected_max_question + 1))
    missing_questions = sorted(expected_questions - set(normalized_answer_key.keys()))

    if missing_questions:
        print(
            f"Error: {field_name} is incomplete. "
            f"Missing questions: {', '.join(map(str, missing_questions))}."
        )
        return None

    return normalized_answer_key


def _normalize_standards(standards, question_count):
    normalized_standards = {
        str(question_number): []
        for question_number in range(1, question_count + 1)
    }

    if standards is None:
        return normalized_standards

    if not isinstance(standards, dict):
        print("Error: 'standards' must be a JSON object when present.")
        return None

    seen_questions = set()
    for key, values in standards.items():
        q_num = _normalize_question_number(key, question_count, "standards")
        if q_num is None:
            return None
        question_key = str(q_num)

        if question_key in seen_questions:
            print(f"Error: Duplicate question number '{q_num}' in standards.")
            return None
        seen_questions.add(question_key)

        if not isinstance(values, list):
            print(f"Error: Standards for question {q_num} must be a list.")
            return None

        normalized_values = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                print(
                    f"Error: Standards for question {q_num} must contain "
                    "non-empty strings only."
                )
                return None
            normalized_values.append(value.strip())

        normalized_standards[question_key] = normalized_values

    return normalized_standards


def load_answer_key(key_path):
    """Loads and validates the JSON answer key file."""
    if not os.path.exists(key_path):
        print(f"Error: Answer key file '{key_path}' not found.")
        return None

    try:
        with open(key_path, encoding="utf-8") as key_file:
            data = json.load(key_file)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse answer key file '{key_path}': {e}")
        return None
    except Exception as e:
        print(f"Error: Could not read answer key file '{key_path}': {e}")
        return None

    if not isinstance(data, dict):
        print(f"Error: Answer key file '{key_path}' must contain a JSON object.")
        return None

    return _normalize_answer_key(data, field_name="answer key")


def load_assignment(assignment_path):
    """Loads and validates a richer assignment JSON format."""
    if not os.path.exists(assignment_path):
        print(f"Error: Assignment file '{assignment_path}' not found.")
        return None

    try:
        with open(assignment_path, encoding="utf-8") as assignment_file:
            data = json.load(assignment_file)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse assignment file '{assignment_path}': {e}")
        return None
    except Exception as e:
        print(f"Error: Could not read assignment file '{assignment_path}': {e}")
        return None

    if not isinstance(data, dict):
        print(f"Error: Assignment file '{assignment_path}' must contain a JSON object.")
        return None

    return validate_assignment_data(data)


def validate_assignment_data(data):
    """Validate assignment data already loaded in memory."""
    if not isinstance(data.get("assignment_id"), str) or not data["assignment_id"].strip():
        print("Error: 'assignment_id' must be a non-empty string.")
        return None
    assignment_id = data["assignment_id"].strip()
    if not validate_identifier("assignment_id", assignment_id, context="assignment"):
        return None

    if not isinstance(data.get("title"), str) or not data["title"].strip():
        print("Error: 'title' must be a non-empty string.")
        return None

    question_count = data.get("question_count")
    if not isinstance(question_count, int) or question_count < 1 or question_count > MAX_QUESTION_COUNT:
        print(f"Error: 'question_count' must be an integer between 1 and {MAX_QUESTION_COUNT}.")
        return None

    choices = data.get("choices")
    if choices != ["A", "B", "C", "D"]:
        print("Error: 'choices' must equal exactly ['A', 'B', 'C', 'D'].")
        return None

    normalized_answer_key = _normalize_answer_key(
        data.get("answer_key"),
        question_count=question_count,
        valid_choices=set(choices),
        field_name="answer_key",
    )
    if normalized_answer_key is None:
        return None

    normalized_standards = _normalize_standards(data.get("standards"), question_count)
    if normalized_standards is None:
        return None

    return {
        "assignment_id": assignment_id,
        "title": data["title"].strip(),
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "answer_key": normalized_answer_key,
        "standards": normalized_standards,
    }
