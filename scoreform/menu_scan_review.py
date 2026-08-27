"""Teacher-facing ScoreForm scan review menu."""

from __future__ import annotations

from scoreform import workspace
from scoreform.assignment import load_assignment
from scoreform.manual_entry import is_manual_entry_cancel, normalize_manual_response
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.scan_review_resolution import (
    RESOLUTION_ACTIONS,
    ScanReviewError,
    _validated_route,
    discover_scan_review_items,
    resolve_scan_review_item,
)
from scoreform.scan_teacher_diagnostics import (
    TeacherScanDiagnostic,
    project_teacher_scan_diagnostic,
)
from scoreform.work_paths import scoreform_work_paths
from scoreform.workflows import clear_screen, pause_for_user, print_menu_header

ACTION_LABELS = {
    "manual_entry": "Enter answers manually",
    "manual_marks": "Record manual marks",
    "rescan_needed": "Mark rescan needed",
    "cannot_route": "Cannot safely route",
    "mixed_assignment": "Mixed assignment source",
    "evidence_filed": "Evidence already filed",
    "dismissed_duplicate": "Dismiss duplicate",
    "other": "Other resolution",
    "defer": "Defer for later",
    "route_selected": "Select existing route",
    "route_corrected": "Correct to existing route",
}

_CANCELLED_HEADINGS = {
    "manual_entry": "Manual Entry Cancelled",
    "manual_marks": "Manual Marks Cancelled",
    "route_selected": "Route Selection Cancelled",
    "route_corrected": "Route Correction Cancelled",
    "evidence_filed": "Evidence Filing Cancelled",
}


def _render_teacher_review(item, diagnostic: TeacherScanDiagnostic) -> None:
    """Render the bounded primary teacher recovery view."""
    print_menu_header("Scan Review")
    print("Problem")
    print(diagnostic.headline)
    print(diagnostic.explanation)
    print()
    print("Evidence")
    print(diagnostic.evidence_message)
    source = item.source_filename
    if item.source_page_number is not None:
        source = f"{source}, page {item.source_page_number}"
    print(f"Source: {source}")
    if diagnostic.diagnostic_artifacts_available:
        print("Diagnostic images are available under Technical details.")
    print()
    print("Recommended next step")
    print(diagnostic.guidance)
    print()


def _render_available_actions(
    actions: tuple[str, ...],
    *,
    recommended_actions: tuple[str, ...],
) -> None:
    """Render actual recovery actions with bounded recommendation markers."""
    recommended = set(recommended_actions)
    print("Available actions")
    for index, action in enumerate(actions, start=1):
        marker = " (recommended)" if action in recommended else ""
        print(f"{index}. {ACTION_LABELS[action]}{marker}")
    print("T. Technical details")


def _render_technical_details(item) -> None:
    """Render exact read-only recovery internals behind the advanced surface."""
    print_menu_header("Technical Scan Details")
    print(f"Failure ID: {item.failure_id}")
    print(f"Failure record: {_shown(item.failure_metadata_relative_path)}")
    print(f"Pipeline stage: {_shown(item.stage)}")
    print(f"Core category: {item.failure_category}")
    print(f"ScoreForm category: {_shown(item.scoreform_failure_category)}")
    print(f"Reason: {item.failure_message}")
    print(f"Source: {item.source_filename}")
    print(f"Source scan ID: {_shown(item.source_scan_id)}")
    print(f"Source page: {_shown(item.source_page_number)}")
    print(f"Source SHA-256: {_shown(item.source_sha256)}")
    print(f"Retained source: {_shown(item.retained_source_path)}")
    print(f"Review copy: {_shown(item.review_copy_path)}")
    identity_label = {
        "validated_target": "Verified target identity",
        "validated_locator": "Validated locator identity",
        "none": "No available identity",
    }.get(item.identity.source, "No available identity")
    print(identity_label)
    print(f"  Class: {_shown(item.identity.class_id)}")
    print(f"  Assignment: {_shown(item.identity.assignment_id)}")
    print(f"  Student: {_shown(item.identity.student_id)}")
    print(f"  Route ID: {_shown(item.identity.route_id)}")
    print(f"  Page ID: {_shown(item.identity.page_id)}")
    print(f"  Issuance ID: {_shown(item.identity.issuance_id)}")
    print(f"  Logical page: {_shown(item.identity.logical_page)}")
    print(f"  Total pages: {_shown(item.identity.total_pages)}")
    if item.diagnostic_identity.source == "scoreform_diagnostic":
        print("Observed diagnostic identity")
        print(f"  Class: {_shown(item.diagnostic_identity.class_id)}")
        print(f"  Assignment: {_shown(item.diagnostic_identity.assignment_id)}")
        print(f"  Student: {_shown(item.diagnostic_identity.student_id)}")
    print(f"Raw payload: {ascii(item.detected_payload)}")
    if item.route_locator is not None:
        print(f"Validated route: {item.route_locator.route_id}")
    if item.target is not None:
        print(f"Validated target: {item.target.record_id}")
    details = item.details
    if details is not None:
        print(f"Failure origin: {details.failure_origin}")
        if details.diagnostic_paths:
            print("Diagnostic artifacts:")
            for path in details.diagnostic_paths:
                print(f"  {path}")
        if details.diagnostic_errors:
            print("Diagnostic errors:")
            for error in details.diagnostic_errors:
                error_type = _shown(error.get("error_type"))
                message = _shown(error.get("error_message"))
                print(f"  {error_type}: {message}")
    print(f"Resolution history ({len(item.resolution_history)}):")
    for resolution in item.resolution_history:
        print(
            f"  {resolution.resolved_at}: {resolution.resolution_status} / "
            f"{resolution.resolution_action}"
        )
    if item.latest_resolution_details is not None:
        latest = item.latest_resolution_details
        if latest.identity_source == "teacher_verified":
            print("Teacher-verified resolution identity")
            print(f"  Class: {_shown(latest.identity.get('class_id'))}")
            print(f"  Assignment: {_shown(latest.identity.get('assignment_id'))}")
            print(f"  Student: {_shown(latest.identity.get('student_id'))}")


def _render_cancelled_action(action: str) -> None:
    """Report an abandoned review action without implying rollback."""
    print_menu_header(_CANCELLED_HEADINGS.get(action, "Scan Review Not Updated"))
    print("No result or resolution record was written.")
    print("Existing retained evidence and earlier review history remain unchanged.")


def _shown(value) -> str:
    return str(value) if value not in (None, "") else "—"


def _prompt_identity(item):
    print("Paper identity")
    print("Enter only identity verified from the paper or retained evidence.")
    print()
    class_id = input(f"Class [{_shown(item.class_id)}]: ").strip() or item.class_id
    assignment_id = (
        input(f"Assignment [{_shown(item.assignment_id)}]: ").strip()
        or item.assignment_id
    )
    student_id = (
        input(f"Student [{_shown(item.student_id)}]: ").strip() or item.student_id
    )
    return class_id, assignment_id, student_id


def _prompt_manual_answers(root, item, identity):
    # Validation and assignment loading happen in the service; read just enough here
    # to collect a complete set before any result or resolution is written.
    class_id, assignment_id, _student_id = identity
    if not class_id or not assignment_id:
        raise ScanReviewError("Manual entry requires class and assignment identity.")
    assignment = load_assignment(
        scoreform_work_paths(root, class_id, assignment_id).assignment_path
    )
    if assignment is None:
        raise ScanReviewError("The selected assignment could not be loaded.")
    clear_screen()
    print_menu_header("Manual Entry")
    print(f"Questions: {assignment['question_count']}")
    print("Enter A, B, C, or D for each question.")
    print()
    answers = {}
    for question in range(1, assignment["question_count"] + 1):
        while True:
            raw = input(f"Question {question}: ")
            if is_manual_entry_cancel(raw):
                return None
            answer = normalize_manual_response(raw)
            if answer is not None:
                answers[question] = answer
                break
            print("Enter A-D, blank, ambiguous, or cancel.")
    clear_screen()
    print_menu_header("Confirm Manual Entry")
    print("Answers:")
    print("  " + "  ".join(f"{q}:{a}" for q, a in answers.items()))
    print()
    if input("Type WRITE to save the result: ").strip() != "WRITE":
        return None
    return answers


def allowed_review_actions(root, item) -> tuple[str, ...]:
    allowed = [
        "route_selected",
        "route_corrected",
        "rescan_needed",
        "cannot_route",
        "mixed_assignment",
        "evidence_filed",
        "other",
        "defer",
    ]
    if item.scoreform_failure_category in {
        "duplicate_page",
        "duplicate_route",
        "conflicting_duplicate",
    }:
        allowed.append("dismissed_duplicate")
    if item.class_id and item.assignment_id:
        assignment = load_assignment(
            scoreform_work_paths(
                root, item.class_id, item.assignment_id
            ).assignment_path
        )
        if assignment is not None:
            allowed.append("manual_marks")
            if item.student_id:
                allowed.append("manual_entry")
    return tuple(action for action in RESOLUTION_ACTIONS if action in allowed)


def _perform_action(root, item, action):
    clear_screen()
    print_menu_header(ACTION_LABELS[action])
    identity = (None, None, None)
    if action in {"manual_entry", "manual_marks"}:
        identity = _prompt_identity(item)
    evidence_path = None
    route_payload = None
    if action in {"route_selected", "route_corrected"}:
        route_payload = input("Exact canonical PDS2 route payload: ").strip()
    if action == "evidence_filed":
        evidence_path = input("Workspace-relative evidence path: ").strip()
    elif action in {"manual_entry", "manual_marks"}:
        evidence_path = (
            input(
                "Alternate workspace-relative evidence path (blank uses retained source): "
            ).strip()
            or None
        )
    message = None
    if action == "other":
        message = input("Resolution note: ").strip()
    elif action in {"manual_entry", "manual_marks"}:
        message = input("Teacher note (blank uses default): ").strip() or None
    answers = None
    assignment = None
    if action == "manual_entry":
        answers = _prompt_manual_answers(root, item, identity)
        if answers is None:
            return None
        assignment = load_assignment(
            scoreform_work_paths(root, identity[0], identity[1]).assignment_path
        )
    final_locator = item.route_locator
    final_target = item.target
    if route_payload is not None:
        final_locator, final_target, _context = _validated_route(root, route_payload)
    print()
    print(f"Failure: {item.failure_id}")
    print(f"Current status: {item.status}")
    print(f"Action: {action}")
    print(f"Final locator: {_shown(getattr(final_locator, 'route_id', None))}")
    print(f"Final target: {_shown(getattr(final_target, 'record_id', None))}")
    print(
        "Verified or teacher-entered identity: "
        f"class={_shown(identity[0])}, assignment={_shown(identity[1])}, "
        f"student={_shown(identity[2])}"
    )
    if answers is not None:
        assert assignment is not None
        score = sum(
            answer == assignment["answer_key"][str(question)]
            for question, answer in answers.items()
        )
        print(f"Manual score/total: {score}/{assignment['question_count']}")
        print(
            "Result destination: "
            f"classes/{identity[0]}/modules/scoreform/work/{identity[1]}/results.csv"
        )
    selected_evidence = evidence_path or (
        item.retained_source_path if action in {"manual_entry", "manual_marks"} else None
    )
    print(f"Evidence source: {_shown(selected_evidence)}")
    if action in {"manual_entry", "manual_marks"}:
        print(
            "Evidence destination: "
            f"classes/{identity[0]}/modules/scoreform/work/{identity[1]}/scans/"
            f"<non-overwriting _{action} copy>"
        )
    elif action == "evidence_filed":
        print(f"Evidence destination: {_shown(evidence_path)}")
    else:
        print("Evidence destination: —")
    if input("Type WRITE to append this resolution: ").strip() != "WRITE":
        return None
    return resolve_scan_review_item(
        root,
        item.failure_id,
        action,
        message=message,
        evidence_path=evidence_path,
        class_id=identity[0],
        assignment_id=identity[1],
        student_id=identity[2],
        answers=answers,
        route_payload=route_payload,
    )


def launch_scan_review_menu(*, source_scan_id: str | None = None) -> int:
    """List active review items, optionally scoped to one exact retained source."""
    root = workspace.get_scoreform_workspace_root()
    while True:
        clear_screen()
        if source_scan_id is None:
            print_menu_header("Resolve Scan Review Items")
            discovery = discover_scan_review_items(root)
        else:
            print_menu_header("Review This Scan")
            print("Scope: unresolved or deferred ScoreForm items from this retained scan only.")
            print()
            discovery = discover_scan_review_items(
                root,
                source_scan_id=source_scan_id,
            )
        if not discovery.items:
            if source_scan_id is None:
                print("No unresolved or deferred ScoreForm scan review items.")
            else:
                print(
                    "No unresolved or deferred ScoreForm review items remain "
                    "for this retained scan."
                )
            print()
            pause_for_user()
            return 0
        for index, item in enumerate(discovery.items, start=1):
            page = (
                f", page {item.source_page_number}" if item.source_page_number else ""
            )
            print(
                f"{index}. {item.status}: {item.failure_category} — "
                f"{item.source_filename}{page}"
            )
        if source_scan_id is None and discovery.warning_count:
            print(f"Warning: {discovery.warning_count} review record(s) ignored.")
            print(f"  Invalid failures: {discovery.invalid_failure_count}")
            print(f"  Invalid resolutions: {discovery.invalid_resolution_count}")
            print(
                "  Unsupported v1 failures: "
                f"{discovery.unsupported_v1_failure_count}"
            )
            print(
                "  Unsupported v1 resolutions: "
                f"{discovery.unsupported_v1_resolution_count}"
            )
            print(f"  Orphan resolutions: {discovery.orphan_resolution_count}")
            print(f"  Provenance mismatches: {discovery.provenance_mismatch_count}")
            print(
                "  Malformed ScoreForm details: "
                f"{discovery.malformed_scoreform_details_count}"
            )
            print(f"  Foreign records: {discovery.foreign_record_count}")
        print_scoreform_navigation_options()
        print()
        choice = input("Select an item: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return 0
        if not choice.isdigit() or not 1 <= int(choice) <= len(discovery.items):
            print("Select a listed review item.")
            pause_for_user()
            continue
        item = discovery.items[int(choice) - 1]
        while True:
            actions = allowed_review_actions(root, item)
            diagnostic = project_teacher_scan_diagnostic(
                item,
                allowed_actions=actions,
            )
            clear_screen()
            _render_teacher_review(item, diagnostic)
            _render_available_actions(
                actions,
                recommended_actions=diagnostic.recommended_actions,
            )
            print_scoreform_navigation_options()
            print()
            action_choice = input("Select an action: ").strip()
            if action_choice.casefold() == "t":
                clear_screen()
                _render_technical_details(item)
                print()
                pause_for_user()
                continue
            if parse_scoreform_navigation(action_choice) is not None:
                break
            if (
                not action_choice.isdigit()
                or not 1 <= int(action_choice) <= len(actions)
            ):
                print("Select a listed action or T for technical details.")
                pause_for_user()
                continue
            action = actions[int(action_choice) - 1]
            try:
                result = _perform_action(root, item, action)
            except (ScanReviewError, OSError) as error:
                clear_screen()
                print_menu_header("Scan Review Not Updated")
                print(f"Error: {error}")
                print()
                pause_for_user()
                break
            if result is None:
                clear_screen()
                _render_cancelled_action(action)
            else:
                clear_screen()
                print_menu_header("Scan Review Updated")
                print(f"Status: {result.resolution_status}")
                print(
                    "Resolution record: "
                    f"{result.resolution_metadata_relative_path}"
                )
                if result.evidence_path:
                    print(f"Evidence: {result.evidence_path}")
                if result.result_written:
                    print("Manual-entry result written to assignment results.")
            print()
            pause_for_user()
            break
