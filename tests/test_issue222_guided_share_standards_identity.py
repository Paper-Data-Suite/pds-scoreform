"""Issue #222 guided Share Results regression for Core Standards identity."""

from __future__ import annotations

import json

from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    write_workspace_standards_library,
)

from scoreform.academic_result_manifest_generation import (
    load_academic_result_manifest_revision,
)
from scoreform.guided_share_results import (
    ShareResultsNextStep,
    commit_share_results_manifest,
    commit_share_results_publication,
    commit_share_results_registration,
    plan_share_results_readiness,
    prepare_share_results_manifest,
    prepare_share_results_publication,
    prepare_share_results_registration,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.work_paths import scoreform_work_paths

CLASS_ID = "english_12_pd2"
ASSIGNMENT_ID = "scene_summary_and_pacing_check"
PROFILE_ID = "english12.njsls.2023"
STANDARD_IDS = (
    "njsls-ela:RL.TS.11-12.4",
    "njsls-ela:W.NW.11-12.3.D",
)


def _prepare_workspace(tmp_path) -> None:
    write_workspace_standards_library(
        tmp_path,
        StandardsLibrary(
            standards=(
                StandardDefinition(
                    standard_id=STANDARD_IDS[0],
                    code="RL.TS.11-12.4",
                    source="NJSLS-ELA 2023",
                    short_name="Text Structure",
                    description="Analyze structural choices and their effects.",
                ),
                StandardDefinition(
                    standard_id=STANDARD_IDS[1],
                    code="W.NW.11-12.3.D",
                    source="NJSLS-ELA 2023",
                    short_name="Narrative Technique",
                    description="Use precise words, details, and sensory language.",
                ),
            ),
            profiles=(
                StandardsProfile(
                    profile_id=PROFILE_ID,
                    standards=STANDARD_IDS,
                    subject="English Language Arts",
                    course="English 12",
                ),
            ),
        ),
    )

    paths = scoreform_work_paths(tmp_path, CLASS_ID, ASSIGNMENT_ID)
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": ASSIGNMENT_ID,
                "title": "Scene, Summary, and Pacing Check",
                "question_count": 2,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A", "2": "B"},
                "standards_profile_id": PROFILE_ID,
                "standards": {
                    "1": [STANDARD_IDS[0]],
                    "2": [STANDARD_IDS[1]],
                },
            }
        ),
        encoding="utf-8",
    )

    result = ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
        student_id="student_001",
        last_name="Synthetic",
        first_name="Learner",
        period="2",
        page_display="manual",
        score=1,
        total_points=2,
        answers=(
            ScoredAnswer(1, "A", True),
            ScoredAnswer(2, "BLANK", False),
        ),
        source_file="plain_paper_manual_entry",
    )
    assert export_scoreform_result_models(
        (result,),
        workspace_root=tmp_path,
    ).succeeded


def test_guided_share_results_publishes_core_valid_punctuation_standards(
    tmp_path,
) -> None:
    _prepare_workspace(tmp_path)

    readiness = plan_share_results_readiness(
        tmp_path,
        CLASS_ID,
        ASSIGNMENT_ID,
    )
    assert readiness.next_step is ShareResultsNextStep.REGISTER

    registration_preview = prepare_share_results_registration(
        tmp_path,
        CLASS_ID,
        ASSIGNMENT_ID,
        academic_intent="formative",
        lifecycle="active",
    )
    registration = commit_share_results_registration(
        tmp_path,
        registration_preview,
    )
    assert registration.registration.registration_revision == 1

    readiness = plan_share_results_readiness(
        tmp_path,
        CLASS_ID,
        ASSIGNMENT_ID,
    )
    assert readiness.next_step is ShareResultsNextStep.GENERATE_MANIFEST

    manifest_preview = prepare_share_results_manifest(
        tmp_path,
        CLASS_ID,
        ASSIGNMENT_ID,
    )
    manifest_outcome = commit_share_results_manifest(
        tmp_path,
        manifest_preview,
    )
    assert manifest_outcome.revision == 1
    assert manifest_outcome.created_new_revision

    stored = load_academic_result_manifest_revision(
        tmp_path,
        readiness.work,
        1,
    )
    assert stored.manifest.assignment.standards_profile_id == PROFILE_ID
    assert stored.manifest.assignment.questions[0].standard_ids == (
        STANDARD_IDS[0],
    )
    assert stored.manifest.assignment.questions[1].standard_ids == (
        STANDARD_IDS[1],
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        CLASS_ID,
        ASSIGNMENT_ID,
    )
    assert readiness.next_step is ShareResultsNextStep.PUBLISH_FIRST
    assert readiness.producer_head_revision == 1
    assert readiness.core_head_publication_id is None

    publication_preview = prepare_share_results_publication(
        tmp_path,
        CLASS_ID,
        ASSIGNMENT_ID,
    )
    publication_outcome = commit_share_results_publication(
        tmp_path,
        publication_preview,
    )
    assert publication_outcome.disposition == "created"
    assert publication_outcome.manifest_revision == 1
    assert publication_outcome.available_for_meridian_consumption

    readiness = plan_share_results_readiness(
        tmp_path,
        CLASS_ID,
        ASSIGNMENT_ID,
    )
    assert readiness.next_step is ShareResultsNextStep.ALREADY_CURRENT
    assert readiness.producer_head_revision == 1
    assert readiness.core_head_revision == 1
    assert readiness.catalog_available

    stored_after_publication = load_academic_result_manifest_revision(
        tmp_path,
        readiness.work,
        1,
    )
    assert stored_after_publication.content == stored.content
    assert stored_after_publication.sha256 == stored.sha256
    assert (
        stored_after_publication.manifest.assignment.questions[0].standard_ids
        == (STANDARD_IDS[0],)
    )
    assert (
        stored_after_publication.manifest.assignment.questions[1].standard_ids
        == (STANDARD_IDS[1],)
    )
