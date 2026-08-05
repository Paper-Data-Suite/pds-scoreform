"""Direct CLI surface for ScoreForm Academic Work Registration."""

from __future__ import annotations

from collections.abc import Sequence

from scoreform import workspace
from scoreform.academic_work_registration import (
    SUPPORTED_ACADEMIC_INTENTS,
    SUPPORTED_ACADEMIC_WORK_LIFECYCLES,
    ScoreFormAcademicWorkRegistrationError,
    ScoreFormAcademicWorkRegistrationPartialSuccessError,
    ScoreFormAcademicWorkRegistrationValidationError,
    load_current_scoreform_academic_work_registration,
    register_scoreform_academic_work,
    update_scoreform_academic_work_registration,
)

ACADEMIC_WORK_USAGE = """Usage:
  scoreform academic-work show --class-id <class_id> --assignment-id <assignment_id>
  scoreform academic-work register --class-id <class_id> --assignment-id <assignment_id> --academic-intent <intent> --lifecycle <lifecycle>
  scoreform academic-work update --class-id <class_id> --assignment-id <assignment_id> --academic-intent <intent> --lifecycle <lifecycle> --expected-current-revision <revision>"""


def print_academic_work_help() -> None:
    print(ACADEMIC_WORK_USAGE)
    print()
    print("Academic intents: " + ", ".join(SUPPORTED_ACADEMIC_INTENTS))
    print("Lifecycles: " + ", ".join(SUPPORTED_ACADEMIC_WORK_LIFECYCLES))
    print("Registration is explicit and does not publish results or create a Grade.")


def _parse_options(args: Sequence[str], required: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token not in required:
            if token.startswith("--"):
                raise ScoreFormAcademicWorkRegistrationValidationError(
                    f"Unknown option: {token}."
                )
            raise ScoreFormAcademicWorkRegistrationValidationError(
                f"Unexpected positional argument: {token}."
            )
        if token in values:
            raise ScoreFormAcademicWorkRegistrationValidationError(
                f"Duplicate option: {token}."
            )
        if index + 1 >= len(args) or args[index + 1].startswith("--"):
            raise ScoreFormAcademicWorkRegistrationValidationError(
                f"Missing value for {token}."
            )
        values[token] = args[index + 1]
        index += 2
    missing = [option for option in required if option not in values]
    if missing:
        raise ScoreFormAcademicWorkRegistrationValidationError(
            "Missing required option(s): " + ", ".join(missing) + "."
        )
    return values


def _print_registration(registration, *, status: str = "registered") -> None:
    print(f"module_id: {registration.work.module_id}")
    print(f"class_id: {registration.work.class_id}")
    print(f"assignment_id: {registration.work.work_id}")
    print(f"registration status: {status}")
    print(f"registration revision: {registration.registration_revision}")
    print(f"producer contract version: {registration.producer_contract_version}")
    print(f"title: {registration.title}")
    print(f"work kind: {registration.work_kind}")
    print(f"academic intent: {registration.academic_intent}")
    print(f"lifecycle: {registration.lifecycle}")
    print(f"created_at: {registration.created_at.isoformat()}")
    print(f"updated_at: {registration.updated_at.isoformat()}")
    print("source records:")
    for source in registration.source_records:
        contract_version = source.contract_version
        rendered_contract = "null" if contract_version is None else contract_version
        print(
            "  - "
            f"module_id={source.module_id}, record_kind={source.record_kind}, "
            f"record_id={source.record_id}, contract_version={rendered_contract}"
        )


def _print_failure(error: ScoreFormAcademicWorkRegistrationError) -> None:
    print(f"Error: {error}")
    if isinstance(error, ScoreFormAcademicWorkRegistrationPartialSuccessError):
        state = error.state
        print("Warning: durable Core registry state may exist.")
        print(f"operation: {state.operation}")
        if state.registration is not None:
            print(
                "registration revision: "
                f"{state.registration.registration_revision}"
            )
        if state.canonical_path is not None:
            print(f"canonical path: {state.canonical_path}")
        if state.current_selected is not None:
            print(f"current selected: {'yes' if state.current_selected else 'no'}")
        print("Inspect or validate the Core registry before retrying.")


def run_academic_work(args: Sequence[str]) -> int:
    """Dispatch ``scoreform academic-work`` without traceback on expected errors."""
    if not args or args[0] in {"help", "--help", "-h"}:
        print_academic_work_help()
        return 0 if args else 1
    action = args[0]
    if action not in {"show", "register", "update"}:
        print(f"Error: Unknown academic-work command: {action}.")
        print_academic_work_help()
        return 1

    common = ("--class-id", "--assignment-id")
    required: tuple[str, ...]
    if action in {"register", "update"}:
        required = common + ("--academic-intent", "--lifecycle")
    else:
        required = common
    if action == "update":
        required += ("--expected-current-revision",)

    try:
        values = _parse_options(args[1:], required)
        workspace_root = workspace.get_scoreform_workspace_root()
        class_id = values["--class-id"]
        assignment_id = values["--assignment-id"]
        if action == "show":
            registration = load_current_scoreform_academic_work_registration(
                workspace_root, class_id, assignment_id
            )
            if registration is None:
                print("module_id: scoreform")
                print(f"class_id: {class_id}")
                print(f"assignment_id: {assignment_id}")
                print("registration status: not registered")
                return 1
            _print_registration(registration)
            return 0

        intent = values["--academic-intent"]
        lifecycle = values["--lifecycle"]
        if intent not in SUPPORTED_ACADEMIC_INTENTS:
            raise ScoreFormAcademicWorkRegistrationValidationError(
                "academic_intent must be one of: "
                + ", ".join(SUPPORTED_ACADEMIC_INTENTS)
                + "."
            )
        if lifecycle not in SUPPORTED_ACADEMIC_WORK_LIFECYCLES:
            raise ScoreFormAcademicWorkRegistrationValidationError(
                "lifecycle must be one of: "
                + ", ".join(SUPPORTED_ACADEMIC_WORK_LIFECYCLES)
                + "."
            )
        if action == "register":
            result = register_scoreform_academic_work(
                workspace_root,
                class_id,
                assignment_id,
                academic_intent=intent,
                lifecycle=lifecycle,
            )
        else:
            revision_text = values["--expected-current-revision"]
            if not revision_text.isdecimal():
                raise ScoreFormAcademicWorkRegistrationValidationError(
                    "expected_current_revision must be a positive integer."
                )
            revision = int(revision_text)
            if revision < 1:
                raise ScoreFormAcademicWorkRegistrationValidationError(
                    "expected_current_revision must be a positive integer."
                )
            result = update_scoreform_academic_work_registration(
                workspace_root,
                class_id,
                assignment_id,
                academic_intent=intent,
                lifecycle=lifecycle,
                expected_current_revision=revision,
            )
        print(f"disposition: {result.disposition}")
        _print_registration(result.registration)
        return 0
    except ScoreFormAcademicWorkRegistrationError as error:
        _print_failure(error)
        print()
        print(ACADEMIC_WORK_USAGE)
        return 1
