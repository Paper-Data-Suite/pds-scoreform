import os
import json
from scoreform.config import MAX_QUESTION_COUNT
from scoreform.validation import validate_identifier


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


def _normalize_standards(standards, question_count):
    if standards is None:
        return {}

    if not isinstance(standards, dict):
        print("Error: 'standards' must be a JSON object when present.")
        return None

    normalized_standards = {}
    for key, values in standards.items():
        q_num = _normalize_question_number(key, question_count, "standards")
        if q_num is None:
            return None

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

        normalized_standards[q_num] = normalized_values

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

    answer_key = {}
    for key, value in data.items():
        if isinstance(key, str) and key.isdigit():
            q_num = int(key)
        elif isinstance(key, int):
            q_num = key
        else:
            print(
                f"Error: Invalid question number in answer key: {key!r}. "
                f"Question numbers must be 1 through {MAX_QUESTION_COUNT}."
            )
            return None

        if q_num < 1 or q_num > MAX_QUESTION_COUNT:
            print(
                f"Error: Invalid question number '{q_num}' in answer key. "
                f"Question numbers must be 1 through {MAX_QUESTION_COUNT}."
            )
            return None

        if not isinstance(value, str) or value.strip().upper() not in {"A", "B", "C", "D"}:
            print(
                f"Error: Invalid answer for question {q_num}: {value!r}. "
                "Answers must be A, B, C, or D."
            )
            return None

        answer_key[q_num] = value.strip().upper()

    if not answer_key:
        print("Error: Answer key must contain at least one question.")
        return None

    max_question = max(answer_key.keys())
    expected_questions = set(range(1, max_question + 1))
    missing_questions = sorted(expected_questions - set(answer_key.keys()))

    if missing_questions:
        print(
            "Error: Answer key is incomplete. "
            f"Missing questions: {', '.join(map(str, missing_questions))}."
        )
        return None

    return answer_key


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

    answer_key = data.get("answer_key")
    if not isinstance(answer_key, dict):
        print("Error: 'answer_key' must be a JSON object.")
        return None

    if len(answer_key) != question_count:
        print(
            f"Error: 'answer_key' must contain exactly {question_count} entries."
        )
        return None

    normalized_answer_key = {}
    for key, value in answer_key.items():
        if isinstance(key, str) and key.isdigit():
            q_num = int(key)
        elif isinstance(key, int):
            q_num = key
        else:
            print(
                f"Error: Invalid question number in answer_key: {key!r}. "
                f"Question numbers must be 1 through {question_count}."
            )
            return None

        if q_num < 1 or q_num > question_count:
            print(
                f"Error: Invalid question number '{q_num}' in answer_key. "
                f"Question numbers must be 1 through {question_count}."
            )
            return None

        if not isinstance(value, str) or value.strip().upper() not in {"A", "B", "C", "D"}:
            print(
                f"Error: Invalid answer for question {q_num}: {value!r}. "
                "Answers must be A, B, C, or D."
            )
            return None

        normalized_answer_key[q_num] = value.strip().upper()

    missing_questions = sorted(set(range(1, question_count + 1)) - set(normalized_answer_key.keys()))
    if missing_questions:
        print(
            "Error: answer_key is incomplete. "
            f"Missing questions: {', '.join(map(str, missing_questions))}."
        )
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
