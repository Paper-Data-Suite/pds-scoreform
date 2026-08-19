from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from unittest.mock import patch

from scoreform import (
    assignment_workflows,
    menu_academic_work,
    menu_manifest,
    menu_publication,
)

BASELINE_COMMIT = "047e47f60730b8a5540b5e1d92f008ffad37eede"
ASSIGNMENT_MENU_LABELS = (
    "1. Create an assignment",
    "2. Edit an assignment",
    "3. Validate an assignment file",
    "4. Generate answer sheets",
    "5. Score scanned responses",
    "6. View assignment results",
    "7. Decode QR from a file",
    "8. Enter Plain-Paper Results",
    "9. Resolve scan review items",
    "10. Academic Work Registration",
    "11. Academic Result Manifests",
    "12. Academic Result Publications",
)


def _distribution_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _capture_assignment_menu() -> dict[str, object]:
    stream = io.StringIO()
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return "B"

    with (
        patch.object(assignment_workflows, "clear_screen", lambda: None),
        patch("builtins.input", fake_input),
        contextlib.redirect_stdout(stream),
    ):
        result = assignment_workflows.launch_assignment_menu()

    output = stream.getvalue()
    missing = [label for label in ASSIGNMENT_MENU_LABELS if label not in output]
    if missing:
        raise AssertionError(f"Assignment menu baseline changed; missing: {missing}")
    positions = [output.index(label) for label in ASSIGNMENT_MENU_LABELS]
    if positions != sorted(positions):
        raise AssertionError("Assignment menu labels are not in the v0.10.0 baseline order.")
    return {
        "exit_code": result,
        "top_level_option_count": len(ASSIGNMENT_MENU_LABELS),
        "prompt_count": len(prompts),
    }


def _synthetic_classes():
    return [{"class_id": "audit_class_1", "roster": {"students": []}}]


def _synthetic_assignments(_class_id: str):
    return [
        {
            "assignment_id": "audit_quiz_10",
            "assignment": {"title": "Synthetic Audit Quiz"},
        }
    ]


def _capture_selector(selector, module) -> dict[str, object]:
    prompts: list[str] = []
    answers = iter(("1", "1"))

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    with (
        patch.object(module, "discover_class_rosters", _synthetic_classes),
        patch.object(module, "discover_class_assignments", _synthetic_assignments),
        patch("builtins.input", fake_input),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        selected = selector()

    if selected is None:
        raise AssertionError(f"{module.__name__} selector unexpectedly cancelled.")
    return {
        "prompts": prompts,
        "class_prompt_count": sum("class" in prompt.lower() for prompt in prompts),
        "assignment_prompt_count": sum("assignment" in prompt.lower() for prompt in prompts),
    }


def _capture_registration_selector() -> dict[str, object]:
    prompts: list[str] = []
    answers = iter(("1", "1", "3"))

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    with (
        patch.object(menu_academic_work, "discover_class_rosters", _synthetic_classes),
        patch.object(menu_academic_work, "discover_class_assignments", _synthetic_assignments),
        patch.object(
            menu_academic_work.workspace,
            "get_scoreform_workspace_root",
            lambda: "synthetic-workspace",
        ),
        patch.object(
            menu_academic_work,
            "load_current_scoreform_academic_work_registration",
            lambda *_args, **_kwargs: None,
        ),
        patch("builtins.input", fake_input),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        result = menu_academic_work.launch_academic_work_registration_menu()

    if result != 0:
        raise AssertionError(f"Registration selector audit returned {result!r}.")
    return {
        "prompts": prompts,
        "class_prompt_count": sum("class" in prompt.lower() for prompt in prompts),
        "assignment_prompt_count": sum("assignment" in prompt.lower() for prompt in prompts),
    }


def _capture_results_selector() -> dict[str, object]:
    prompts: list[str] = []
    answers = iter(("1", "1"))

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    assignments = [
        {
            "assignment_id": "audit_quiz_10",
            "assignment": {"title": "Synthetic Audit Quiz"},
            "results_path": "synthetic-results.csv",
        }
    ]
    with (
        patch.object(assignment_workflows, "discover_class_rosters", _synthetic_classes),
        patch.object(
            assignment_workflows,
            "discover_class_assignments",
            lambda _class_id: assignments,
        ),
        patch.object(assignment_workflows, "clear_screen", lambda: None),
        patch.object(
            assignment_workflows,
            "load_assignment_results",
            lambda _path: [],
        ),
        patch("builtins.input", fake_input),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        result = assignment_workflows.launch_view_assignment_results_menu()

    if result != 0:
        raise AssertionError(f"Results selector audit returned {result!r}.")
    return {
        "prompts": prompts,
        "class_prompt_count": sum("class" in prompt.lower() for prompt in prompts),
        "assignment_prompt_count": sum("assignment" in prompt.lower() for prompt in prompts),
    }


def main() -> int:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    if commit != BASELINE_COMMIT:
        raise SystemExit(
            "Issue #182 baseline capture must run before implementation changes. "
            f"Expected {BASELINE_COMMIT}, got {commit}."
        )

    assignment_menu = _capture_assignment_menu()
    registration = _capture_registration_selector()
    manifest = _capture_selector(menu_manifest._select_assignment, menu_manifest)
    publication = _capture_selector(menu_publication._select_assignment, menu_publication)
    results = _capture_results_selector()

    selectors = (registration, manifest, publication)
    if any(item["class_prompt_count"] != 1 for item in selectors):
        raise AssertionError("Expected each publication-stage workflow to reacquire class context.")
    if any(item["assignment_prompt_count"] != 1 for item in selectors):
        raise AssertionError(
            "Expected each publication-stage workflow to reacquire assignment context."
        )
    if results["class_prompt_count"] != 1 or results["assignment_prompt_count"] != 1:
        raise AssertionError("Expected result review to reacquire class/assignment context.")

    payload = {
        "issue": 182,
        "baseline_commit": commit,
        "baseline_tree": tree,
        "python": sys.version.replace("\n", " "),
        "scoreform_distribution": _distribution_version("scoreform"),
        "pds_core_distribution": _distribution_version("pds-core"),
        "assignment_management": assignment_menu,
        "publication_context_acquisition": {
            "registration": registration,
            "manifest": manifest,
            "publication": publication,
            "total_class_selections": 3,
            "total_assignment_selections": 3,
        },
        "results_context_acquisition": results,
        "status": "PASS",
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
