"""Issue #227 Slice 3: Core v0.6.5 reader-support producer metadata.

All inputs are synthetic.  Core profile discovery must never execute the reader.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import (
    PublicationProducerProfileError,
    PublicationReaderSupport,
    build_publication_producer_registry,
    discover_publication_producer_profiles,
    evaluate_publication_compatibility,
    lookup_publication_reader_support,
    validate_publication_producer_profile,
)
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
)
from scoreform.pds_publication import get_publication_producer_profile

_KIND = "academic_result_set"
_READER = PublicationReaderSupport(
    manifest_contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    distribution_name="scoreform",
    reader_contract_version=SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
)


def test_declared_reader_is_exact_and_immutable() -> None:
    profile = get_publication_producer_profile()
    assert validate_publication_producer_profile(profile) == profile
    assert get_publication_producer_profile() == profile
    assert len(profile.publication_contracts) == 1
    support = profile.publication_contracts[0]
    assert support.publication_kind == _KIND
    assert support.manifest_contract_versions == frozenset(
        {ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION}
    )
    assert support.supported_capabilities == frozenset(
        {"points", "question_evidence", "multiple_attempts"}
    )
    assert support.source_record_contracts == ()
    assert support.allows_missing_source_record is True
    assert support.reader_support == (_READER,)
    assert lookup_publication_reader_support(
        profile, _KIND, ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    ) == _READER
    with pytest.raises((FrozenInstanceError, AttributeError)):
        support.reader_support[0].reader_contract_version = "reader_v2"  # type: ignore[misc]


def test_core_registry_and_discovery_preserve_reader_binding() -> None:
    profile = get_publication_producer_profile()
    registry = build_publication_producer_registry()
    assert registry.get("scoreform") == profile
    discovered = [
        candidate
        for candidate in discover_publication_producer_profiles()
        if candidate.module_id == "scoreform"
    ]
    assert discovered == [profile]
    for value in (registry.get("scoreform"), *discovered):
        assert value is not None
        assert lookup_publication_reader_support(
            value, _KIND, ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
        ) == _READER


def test_manifest_kind_and_absent_declarations_do_not_infer_reader() -> None:
    profile = get_publication_producer_profile()
    assert lookup_publication_reader_support(
        profile, "intervention_record_set", ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    ) is None
    assert lookup_publication_reader_support(
        profile, _KIND, "fictional_manifest_v1"
    ) is None

    support = profile.publication_contracts[0]
    widened = replace(
        support,
        manifest_contract_versions=frozenset(
            {ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION, "fictional_manifest_v1"}
        ),
    )
    widened_profile = replace(profile, publication_contracts=(widened,))
    assert lookup_publication_reader_support(
        widened_profile, _KIND, "fictional_manifest_v1"
    ) is None
    legacy = replace(support, reader_support=())
    legacy_profile = replace(profile, publication_contracts=(legacy,))
    assert lookup_publication_reader_support(
        legacy_profile, _KIND, ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    ) is None


def test_core_rejects_duplicate_or_unbound_reader_metadata() -> None:
    support = get_publication_producer_profile().publication_contracts[0]
    with pytest.raises(PublicationProducerProfileError):
        replace(support, reader_support=(_READER, _READER))
    with pytest.raises(PublicationProducerProfileError):
        replace(
            support,
            reader_support=(
                PublicationReaderSupport(
                    manifest_contract_version="fictional_manifest_v1",
                    distribution_name="scoreform",
                    reader_contract_version=SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
                ),
            ),
        )


def _synthetic_publication() -> tuple[PublicationRecord, AcademicWorkRegistration]:
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    work = ModuleWorkRef("scoreform", "class1", "quiz1")
    publication = PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id="pub_" + "1" * 32,
        work=work,
        source_record=None,
        publication_kind=_KIND,
        capabilities=("points", "question_evidence", "multiple_attempts"),
        record_set_id="academic_results",
        record_set_revision=1,
        manifest_contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        manifest_path=(
            "classes/class1/modules/scoreform/work/quiz1/"
            "exports/manifests/academic_results/1.json"
        ),
        manifest_digest_algorithm="sha256",
        manifest_digest="0" * 64,
        published_at=now,
        academic_work_registration_revision=1,
        supersedes_publication_id=None,
    )
    registration = AcademicWorkRegistration(
        schema_version="1",
        record_type="academic_work_registration",
        work=work,
        registration_revision=1,
        producer_contract_version="scoreform_academic_work_v1",
        title="Synthetic Quiz",
        work_kind="assignment",
        academic_intent="summative",
        lifecycle="active",
        created_at=now,
        updated_at=now,
        source_records=(ModuleRecordRef("scoreform", "assignment", "quiz1", None),),
    )
    return publication, registration


def test_reader_metadata_does_not_change_publication_compatibility() -> None:
    profile = get_publication_producer_profile()
    legacy_support = replace(profile.publication_contracts[0], reader_support=())
    legacy_profile = replace(profile, publication_contracts=(legacy_support,))
    publication, registration = _synthetic_publication()
    for supplied_registration in (registration, None):
        before = evaluate_publication_compatibility(
            publication, legacy_profile, supplied_registration
        )
        after = evaluate_publication_compatibility(
            publication, profile, supplied_registration
        )
        assert before == after
    assert evaluate_publication_compatibility(
        publication, profile, registration
    ).compatible is True


def test_isolated_entry_point_discovery_does_not_import_reader_or_create_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace_must_remain_absent"
    script = r"""
import json
import os
import pathlib
import sys
from pds_core.publication_compatibility import (
    build_publication_producer_registry,
    discover_publication_producer_profiles,
    lookup_publication_reader_support,
)
from scoreform.pds_publication import get_publication_producer_profile
p = get_publication_producer_profile()
d = [v for v in discover_publication_producer_profiles() if v.module_id == "scoreform"]
r = build_publication_producer_registry().get("scoreform")
assert len(d) == 1 and d[0] == r == p
q = lookup_publication_reader_support(
    r, "academic_result_set", "scoreform_academic_result_manifest_v1"
)
print(json.dumps({
    "distribution": q.distribution_name,
    "reader": q.reader_contract_version,
    "workspace_exists": pathlib.Path(os.environ["PDS_WORKSPACE_ROOT"]).exists(),
    "reader_imported": "scoreform.academic_result_reader" in sys.modules,
    "blocked_imports": sorted(
        k for k in sys.modules if k.split(".")[0] in
        ("quillan", "concord", "portia", "pds_meridian", "vitrine")
    ),
    "workflow_imports": sorted(
        k for k in sys.modules if k in (
            "scoreform.academic_result_manifest",
            "scoreform.academic_result_manifest_generation",
            "scoreform.academic_work_registration",
            "scoreform.cli",
        )
    ),
}))
"""
    env = os.environ.copy()
    env["PDS_WORKSPACE_ROOT"] = str(workspace)
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "distribution": "scoreform",
        "reader": SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
        "workspace_exists": False,
        "reader_imported": False,
        "blocked_imports": [],
        "workflow_imports": [],
    }
    assert not workspace.exists()
