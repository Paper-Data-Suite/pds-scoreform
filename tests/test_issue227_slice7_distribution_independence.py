"""Issue #227 Slice 7: synthetic cross-version reader-contract qualifications.

The distribution identities below are *hypothetical labels*. These tests neither
forge installed package metadata nor claim that future wheels have been built.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path

import pytest
from pds_core.publication_compatibility import (
    PublicationProducerProfile,
    PublicationReaderSupport,
    lookup_publication_reader_support,
    validate_publication_producer_profile,
)

from scoreform.academic_result_reader import read_academic_result_manifest
from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
)
from scoreform.pds_publication import get_publication_producer_profile

_KIND = "academic_result_set"
_FIXTURE = (
    Path(__file__).parent
    / "fixtures/publication/scoreform_academic_result_manifest_v1.json"
)


@dataclass(frozen=True)
class _HypotheticalImplementation:
    """A test fixture, NOT a Python distribution or a Core profile field."""

    distribution_version: str
    profile: PublicationProducerProfile


def _reader(profile: PublicationProducerProfile) -> PublicationReaderSupport | None:
    return lookup_publication_reader_support(
        profile, _KIND, ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    )


@pytest.mark.parametrize(
    ("version_a", "version_b"),
    (("0.12.2", "0.12.3"), ("0.12.2", "0.13.0")),
)
def test_hypothetical_distribution_versions_share_exact_reader_contract(
    version_a: str, version_b: str
) -> None:
    base = get_publication_producer_profile()
    a = _HypotheticalImplementation(version_a, replace(base))
    b = _HypotheticalImplementation(version_b, replace(base))
    assert a.distribution_version != b.distribution_version
    assert validate_publication_producer_profile(a.profile) == a.profile
    assert validate_publication_producer_profile(b.profile) == b.profile
    assert _reader(a.profile) == _reader(b.profile) == PublicationReaderSupport(
        manifest_contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        distribution_name="scoreform",
        reader_contract_version=SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
    )
    # Core's metadata describes the reader, not an exact installed build.
    assert "distribution_version" not in {
        item.name for item in fields(a.profile)
    }
    assert "distribution_version" not in {
        item.name for item in fields(_reader(a.profile))  # type: ignore[arg-type]
    }


def test_changed_public_reader_contract_is_not_conflated_with_v1() -> None:
    profile = get_publication_producer_profile()
    original = _reader(profile)
    assert original is not None
    changed = replace(
        original, reader_contract_version="scoreform_academic_result_reader_v2"
    )
    support = replace(profile.publication_contracts[0], reader_support=(changed,))
    candidate = replace(profile, publication_contracts=(support,))
    assert validate_publication_producer_profile(candidate) == candidate
    assert _reader(candidate) == changed
    assert _reader(candidate) != original
    assert changed.manifest_contract_version == original.manifest_contract_version
    assert changed.distribution_name == original.distribution_name


def test_reader_distribution_name_is_not_distribution_version() -> None:
    original = _reader(get_publication_producer_profile())
    assert original is not None
    assert original.distribution_name == "scoreform"
    assert original.reader_contract_version == (
        SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION
    )
    assert not any(char.isdigit() for char in original.distribution_name)
    assert original.reader_contract_version != original.manifest_contract_version


def test_missing_reader_metadata_is_not_inferred_from_manifest_support() -> None:
    profile = get_publication_producer_profile()
    support = replace(profile.publication_contracts[0], reader_support=())
    legacy = replace(profile, publication_contracts=(support,))
    assert validate_publication_producer_profile(legacy) == legacy
    assert ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION in support.manifest_contract_versions
    assert _reader(legacy) is None


def test_widening_manifest_support_does_not_extend_reader_binding() -> None:
    profile = get_publication_producer_profile()
    support = replace(
        profile.publication_contracts[0],
        manifest_contract_versions=frozenset(
            {ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION, "synthetic_manifest_v2"}
        ),
    )
    extended = replace(profile, publication_contracts=(support,))
    assert validate_publication_producer_profile(extended) == extended
    assert _reader(extended) == _reader(profile)
    assert lookup_publication_reader_support(
        extended, _KIND, "synthetic_manifest_v2"
    ) is None
    assert lookup_publication_reader_support(
        extended, "intervention_record_set", ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    ) is None


def test_distribution_label_cannot_change_public_reader_result() -> None:
    raw = _FIXTURE.read_bytes()  # Committed synthetic fixture only.
    manifest = read_academic_result_manifest(raw)
    base = get_publication_producer_profile()
    versions = (
        _HypotheticalImplementation("0.12.2", replace(base)),
        _HypotheticalImplementation("0.13.0", replace(base)),
    )
    observed = []
    for candidate in versions:
        declared = _reader(candidate.profile)
        assert declared is not None
        assert declared.reader_contract_version == (
            SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION
        )
        observed.append(read_academic_result_manifest(raw))
    assert observed == [manifest, manifest]
    assert all(item is not manifest for item in observed)
