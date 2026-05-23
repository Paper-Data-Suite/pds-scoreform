import os
import json

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
                "Question numbers must be 1 through 10."
            )
            return None

        if q_num < 1 or q_num > 10:
            print(
                f"Error: Invalid question number '{q_num}' in answer key. "
                "Question numbers must be 1 through 10."
            )
            return None

        if not isinstance(value, str) or value.strip().upper() not in {"A", "B", "C", "D"}:
            print(
                f"Error: Invalid answer for question {q_num}: {value!r}. "
                "Answers must be A, B, C, or D."
            )
            return None

        answer_key[q_num] = value.strip().upper()

    expected_questions = set(range(1, 11))
    missing_questions = sorted(expected_questions - set(answer_key.keys()))
    extra_questions = sorted(set(answer_key.keys()) - expected_questions)

    if missing_questions or extra_questions:
        if missing_questions:
            print(
                "Error: Answer key is incomplete. "
                f"Missing questions: {', '.join(map(str, missing_questions))}."
            )
        if extra_questions:
            print(
                "Error: Answer key contains invalid question numbers: "
                f"{', '.join(map(str, extra_questions))}."
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

    if not isinstance(data.get("title"), str) or not data["title"].strip():
        print("Error: 'title' must be a non-empty string.")
        return None

    question_count = data.get("question_count")
    if not isinstance(question_count, int) or question_count != 10:
        print("Error: 'question_count' must be 10 for now. Variable question counts will be supported later.")
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

    return {
        "assignment_id": data["assignment_id"].strip(),
        "title": data["title"].strip(),
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "answer_key": normalized_answer_key,
    }
