"""Continuous teacher workflow coverage for ScoreForm issue #191."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from scoreform import menu_share_results
from scoreform.assignment_context import AssignmentContextSession
from scoreform.guided_share_results import (
    ScoreFormShareResultsRegistrationPartialSuccessError,
    ShareResultsNextStep,
    ShareResultsPublicationOutcome,
    ShareResultsRegistrationRecovery,
)

WORK = ModuleWorkRef("scoreform", "english10_p2", "unit_quiz")
PUB_ID = "pub_" + ("1" * 32)
NEXT_ID = "pub_" + ("2" * 32)


def _no_screen() -> None:
    return None


def _record() -> dict[str, object]:
    return {
        "class_id": "english10_p2",
        "assignment_id": "unit_quiz",
        "assignment": {"title": "Unit Quiz"},
    }


def _ready(
    step: ShareResultsNextStep,
    *,
    registration_revision: int | None = 1,
    producer_revision: int | None = None,
    producer_current: bool = False,
    core_revision: int | None = None,
    core_id: str | None = None,
    reason: str | None = None,
):
    return SimpleNamespace(
        work=WORK,
        title="Unit Quiz",
        next_step=step,
        blocking_reason=reason,
        registration_revision=registration_revision,
        producer_head_revision=producer_revision,
        producer_head_is_current=producer_current,
        core_head_revision=core_revision,
        core_head_publication_id=core_id,
    )


def _configure_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> list[AssignmentContextSession]:
    seen: list[AssignmentContextSession] = []

    def select(session, **kwargs):
        seen.append(session)
        return _record()

    monkeypatch.setattr(
        menu_share_results,
        "select_assignment_for_workflow",
        select,
    )
    monkeypatch.setattr(
        menu_share_results.workspace,
        "get_scoreform_workspace_root",
        lambda: Path("C:/synthetic-workspace"),
    )
    return seen


def test_first_publication_is_one_assignment_selection_and_exact_stage_sequence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen = _configure_assignment(monkeypatch)
    states = iter(
        [
            _ready(ShareResultsNextStep.REGISTER, registration_revision=None),
            _ready(ShareResultsNextStep.GENERATE_MANIFEST),
            _ready(
                ShareResultsNextStep.PUBLISH_FIRST,
                producer_revision=1,
                producer_current=True,
            ),
        ]
    )
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: next(states),
    )
    monkeypatch.setattr(
        menu_share_results,
        "SUPPORTED_ACADEMIC_INTENTS",
        ("formative", "summative"),
    )
    monkeypatch.setattr(
        menu_share_results,
        "SUPPORTED_ACADEMIC_WORK_LIFECYCLES",
        ("planned", "active"),
    )

    calls: list[str] = []
    reg_preview = SimpleNamespace(
        work=WORK,
        title="Unit Quiz",
        academic_intent="formative",
        lifecycle="active",
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_registration",
        lambda *args, **kwargs: reg_preview,
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_registration",
        lambda *args, **kwargs: (
            calls.append("REGISTER")
            or SimpleNamespace(
                disposition="created",
                registration=SimpleNamespace(registration_revision=1),
            )
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            producer_head_revision_before=None
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_manifest",
        lambda *args, **kwargs: (
            calls.append("GENERATE")
            or SimpleNamespace(
                revision=1,
                created_new_revision=True,
            )
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_publication",
        lambda *args, **kwargs: SimpleNamespace(manifest_revision=1),
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_publication",
        lambda *args, **kwargs: (
            calls.append("PUBLISH")
            or ShareResultsPublicationOutcome(
                work=WORK,
                disposition="created",
                publication_id=PUB_ID,
                manifest_revision=1,
            )
        ),
    )

    answers = iter(["1", "2", "REGISTER", "GENERATE", "PUBLISH"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    session = AssignmentContextSession()
    assert (
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen,
            context_session=session,
        )
        == 0
    )

    assert seen == [session]
    assert calls == ["REGISTER", "GENERATE", "PUBLISH"]
    output = capsys.readouterr().out
    assert "available for Meridian to consume" in output
    assert "Meridian imported" not in output


def test_already_current_performs_no_publication_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_assignment(monkeypatch)
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: _ready(
            ShareResultsNextStep.ALREADY_CURRENT,
            producer_revision=2,
            producer_current=True,
            core_revision=2,
            core_id=PUB_ID,
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_publication",
        lambda *args, **kwargs: SimpleNamespace(manifest_revision=2),
    )
    calls = {"commit": 0}

    def no_write(*args, **kwargs):
        calls["commit"] += 1
        return ShareResultsPublicationOutcome(
            work=WORK,
            disposition="already_current",
            publication_id=PUB_ID,
            manifest_revision=2,
        )

    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_publication",
        no_write,
    )

    assert (
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen
        )
        == 0
    )
    assert calls["commit"] == 1
    assert "already represents this producer evidence" in capsys.readouterr().out


def test_cancel_after_registration_reports_durable_registration_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_assignment(monkeypatch)
    states = iter(
        [
            _ready(ShareResultsNextStep.REGISTER, registration_revision=None),
            _ready(
                ShareResultsNextStep.GENERATE_MANIFEST,
                registration_revision=1,
            ),
        ]
    )
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: next(states),
    )
    monkeypatch.setattr(
        menu_share_results,
        "SUPPORTED_ACADEMIC_INTENTS",
        ("formative",),
    )
    monkeypatch.setattr(
        menu_share_results,
        "SUPPORTED_ACADEMIC_WORK_LIFECYCLES",
        ("active",),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_registration",
        lambda *args, **kwargs: SimpleNamespace(
            work=WORK,
            title="Unit Quiz",
            academic_intent="formative",
            lifecycle="active",
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_registration",
        lambda *args, **kwargs: SimpleNamespace(
            disposition="created",
            registration=SimpleNamespace(registration_revision=1),
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            producer_head_revision_before=None
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_manifest",
        lambda *args, **kwargs: pytest.fail(
            "manifest must not be written"
        ),
    )

    answers = iter(["1", "1", "REGISTER", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert (
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Registration revision 1 was saved in this guided run." in output
    assert "No Core publication was written." in output


def test_cancel_after_successor_manifest_preserves_current_core_head(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_assignment(monkeypatch)
    states = iter(
        [
            _ready(
                ShareResultsNextStep.GENERATE_MANIFEST,
                producer_revision=1,
                core_revision=1,
                core_id=PUB_ID,
            ),
            _ready(
                ShareResultsNextStep.SUPERSEDE,
                producer_revision=2,
                producer_current=True,
                core_revision=1,
                core_id=PUB_ID,
            ),
        ]
    )
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: next(states),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            producer_head_revision_before=1
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            revision=2,
            created_new_revision=True,
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_supersession",
        lambda *args, **kwargs: SimpleNamespace(
            predecessor_manifest_revision=1,
            successor_manifest_revision=2,
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_supersession",
        lambda *args, **kwargs: pytest.fail(
            "supersession must not be written"
        ),
    )

    answers = iter(["GENERATE", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert (
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Manifest revision 2 is already stored." in output
    assert "Core publication revision 1 remains current." in output
    assert "No supersession was written." in output


def test_withdrawn_head_routes_to_exact_advanced_recovery_without_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_assignment(monkeypatch)
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: _ready(
            ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY,
            producer_revision=1,
            core_revision=1,
            core_id=PUB_ID,
            reason="The current Core publication is withdrawn.",
        ),
    )

    assert (
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "4. Academic Result Publications" in output
    assert "republish-after-withdrawal" in output
    assert "No publication write was attempted" in output


def test_registration_partial_success_stops_before_later_stage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_assignment(monkeypatch)
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: _ready(
            ShareResultsNextStep.REGISTER,
            registration_revision=None,
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "SUPPORTED_ACADEMIC_INTENTS",
        ("formative",),
    )
    monkeypatch.setattr(
        menu_share_results,
        "SUPPORTED_ACADEMIC_WORK_LIFECYCLES",
        ("active",),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_registration",
        lambda *args, **kwargs: SimpleNamespace(
            work=WORK,
            title="Unit Quiz",
            academic_intent="formative",
            lifecycle="active",
        ),
    )

    recovery = ShareResultsRegistrationRecovery(
        durable_registration_revision=1,
        current_selected=True,
        guidance="Reload exact registration state before continuing.",
    )

    def partial(*args, **kwargs):
        raise ScoreFormShareResultsRegistrationPartialSuccessError(recovery)

    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_registration",
        partial,
    )
    answers = iter(["1", "1", "REGISTER"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert (
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "may already be durable" in output
    assert "No later guided stage was attempted." in output


@pytest.mark.parametrize(
    ("navigation", "exception"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_confirmation_uses_shared_main_and_quit_navigation(
    monkeypatch: pytest.MonkeyPatch,
    navigation: str,
    exception: type[Exception],
) -> None:
    _configure_assignment(monkeypatch)
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: _ready(
            ShareResultsNextStep.GENERATE_MANIFEST
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_manifest",
        lambda *args, **kwargs: SimpleNamespace(
            producer_head_revision_before=None
        ),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": navigation)

    with pytest.raises(exception):
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen
        )


def test_supersession_success_reports_previous_publication_as_immutable_history(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_assignment(monkeypatch)
    monkeypatch.setattr(
        menu_share_results,
        "plan_share_results_readiness",
        lambda *args, **kwargs: _ready(
            ShareResultsNextStep.SUPERSEDE,
            producer_revision=2,
            producer_current=True,
            core_revision=1,
            core_id=PUB_ID,
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "prepare_share_results_supersession",
        lambda *args, **kwargs: SimpleNamespace(
            predecessor_manifest_revision=1,
            successor_manifest_revision=2,
        ),
    )
    monkeypatch.setattr(
        menu_share_results,
        "commit_share_results_supersession",
        lambda *args, **kwargs: ShareResultsPublicationOutcome(
            work=WORK,
            disposition="created",
            publication_id=NEXT_ID,
            manifest_revision=2,
            previous_publication_id=PUB_ID,
        ),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "SUPERSEDE")

    assert (
        menu_share_results.launch_share_results_with_meridian(
            clear_screen_fn=_no_screen
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Currently published revision: 1" in output
    assert "New producer revision: 2" in output
    assert "previous publication remains in immutable history" in output.lower()
