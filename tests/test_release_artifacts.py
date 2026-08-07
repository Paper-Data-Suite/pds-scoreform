import csv
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_installed_release import (
    core_version_is_supported,
    validate_core_runtime_versions,
)
from scripts.verify_release_artifacts import (
    ArtifactValidationError,
    validate_dist,
    validate_entry_points_text,
    validate_member_names,
    validate_package_metadata,
    validate_sdist,
    validate_sdist_members,
    validate_wheel,
)


def _package_metadata(
    *,
    name: str = "scoreform",
    version: str = "0.9.1",
    requires_python: str | None = ">=3.11",
    core_requirements: tuple[str, ...] = ("pds-core>=0.6,<0.7",),
) -> str:
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if requires_python is not None:
        lines.append(f"Requires-Python: {requires_python}")
    lines.extend(f"Requires-Dist: {requirement}" for requirement in core_requirements)
    return "\n".join(lines) + "\n\n"


def test_release_member_validation_accepts_expected_sources():
    validate_member_names(
        [
            "scoreform-0.9.1/scoreform/cli.py",
            "scoreform-0.9.1/docs/release_checklist.md",
            "scoreform-0.9.1/examples/sample_roster_english9_p2.csv",
        ]
    )


def test_release_entry_point_metadata_requires_routing_and_publication_groups():
    validate_entry_points_text(
        """[paper_data_suite.publication_producers]\r
scoreform = scoreform.pds_publication:get_publication_producer_profile\r
\r
[paper_data_suite.modules]\r
scoreform = scoreform.pds_module:get_module_profile\r
""",
        "fixture wheel",
    )


@pytest.mark.parametrize(
    "text",
    [
        "[paper_data_suite.modules]\nscoreform = scoreform.pds_module:get_module_profile\n",
        """[paper_data_suite.modules]\nscoreform = scoreform.pds_module:get_module_profile\n
[paper_data_suite.publication_producers]\nscoreform = scoreform.pds_publication:wrong\n""",
        """[paper_data_suite.modules]\nscoreform = scoreform.pds_module:get_module_profile\n
[paper_data_suite.publication_producers]\nother = scoreform.pds_publication:get_publication_producer_profile\n""",
    ],
)
def test_release_entry_point_metadata_rejects_missing_or_wrong_profile(text):
    with pytest.raises(ArtifactValidationError):
        validate_entry_points_text(text, "fixture wheel")


@pytest.mark.parametrize(
    "name",
    [
        "scoreform-0.9.1/.git/config",
        "scoreform-0.9.1/classes/class1/roster.csv",
        "scoreform-0.9.1/local_outputs/debug.png",
        "scoreform-0.9.1/private.patch",
        "scoreform-0.9.1/generated.pdf",
        "scoreform-0.9.1/results.csv",
        "../outside.txt",
        "scoreform-0.9.1/pds_core/__init__.py",
        "scoreform/pds_core/__init__.py",
    ],
)
def test_release_member_validation_rejects_generated_or_private_content(name):
    with pytest.raises(ArtifactValidationError):
        validate_member_names([name])


def test_release_artifact_script_is_repo_relative():
    assert Path("scripts/verify_release_artifacts.py").is_file()


def test_clean_install_contract_names_reader_publication_and_cli_boundaries():
    verifier = Path("scripts/verify_installed_release.py").read_text(encoding="utf-8")
    installer = Path("scripts/validate_release_install.ps1").read_text(encoding="utf-8")
    acceptance = Path("scripts/verify_installed_producer_acceptance.py").read_text(
        encoding="utf-8"
    )
    artifact_verifier = Path("scripts/verify_release_artifacts.py").read_text(
        encoding="utf-8"
    )
    for module in (
        "scoreform.academic_result_reader",
        "scoreform.academic_result_publication",
        "scoreform.cli_publication",
        "scoreform.menu_publication",
    ):
        assert module in verifier
        assert module in installer
    assert "scoreform/academic_result_reader.py" in artifact_verifier
    assert "verify_installed_producer_acceptance.py" in installer
    assert "publish_scoreform_academic_results" in acceptance
    assert "supersede_scoreform_academic_results" in acceptance
    assert "withdraw_scoreform_academic_result_publication" in acceptance
    assert "audit_academic_registry" in acceptance
    for command in (
        "publication --help",
        '"status", "publish", "supersede", "republish-after-withdrawal"',
        '"withdraw", "rebuild-catalog"',
    ):
        assert command in installer
    for forbidden in (
        '"classes"',
        '"registry\\work"',
        '"registry\\publications"',
        '"registry\\withdrawals"',
        '"registry\\catalog.sqlite"',
        '"registry\\.locks"',
        '"exports\\manifests"',
    ):
        assert forbidden in installer


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("scoreform-0.9.1-wrong.whl", "unexpected wheel filename"),
        (
            "scoreform-0.9.1-wrong.tar.gz",
            "unexpected sdist filename",
        ),
    ],
)
def test_release_dist_rejects_incorrect_artifact_filenames(
    tmp_path: Path, filename: str, message: str
):
    if filename.endswith(".whl"):
        (tmp_path / filename).touch()
        (tmp_path / "scoreform-0.9.1.tar.gz").touch()
    else:
        (tmp_path / "scoreform-0.9.1-py3-none-any.whl").touch()
        (tmp_path / filename).touch()

    with pytest.raises(ArtifactValidationError, match=message):
        validate_dist(tmp_path, "0.9.1")


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_release_sdist_rejects_symbolic_and_hard_links(link_type):
    member = tarfile.TarInfo("scoreform-0.9.1/linked.py")
    member.type = link_type
    member.linkname = "../../unsafe-target"

    with pytest.raises(ArtifactValidationError):
        validate_sdist_members([member])


def test_release_wheel_rejects_nested_core_package(tmp_path: Path):
    wheel = tmp_path / "scoreform-0.9.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("vendor/pds_core/__init__.py", "")

    with pytest.raises(ArtifactValidationError, match="bundles pds_core"):
        validate_wheel(wheel, "0.9.1")


def test_release_sdist_rejects_nested_core_package(tmp_path: Path):
    sdist = tmp_path / "scoreform-0.9.1.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("scoreform-0.9.1/vendor/pds_core/__init__.py"))

    with pytest.raises(ArtifactValidationError, match="bundles pds_core"):
        validate_sdist(sdist, "0.9.1")


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_release_sdist_archive_rejects_links(tmp_path: Path, link_type):
    sdist = tmp_path / "scoreform-0.9.1.tar.gz"
    member = tarfile.TarInfo("scoreform-0.9.1/linked.py")
    member.type = link_type
    member.linkname = "../../unsafe-target"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(member)

    with pytest.raises(ArtifactValidationError, match="link"):
        validate_sdist(sdist, "0.9.1")


@pytest.mark.parametrize("version", ["0.6.0", "0.6.1", "0.6.9"])
def test_core_release_specifier_accepts_compatible_versions(version):
    assert core_version_is_supported(version)


@pytest.mark.parametrize("version", ["0.5.9", "0.7.0", "0.6.0a1"])
def test_core_release_specifier_rejects_incompatible_versions(version):
    assert not core_version_is_supported(version)


def test_core_runtime_versions_accept_exact_baseline():
    validate_core_runtime_versions("0.6.0", "0.6.0", "0.6.0")


@pytest.mark.parametrize(
    ("distribution", "module", "expected", "message"),
    [
        ("0.5.9", "0.5.9", None, "does not satisfy"),
        ("0.6.0", "0.6.1", None, "disagree"),
        ("0.6.1", "0.6.1", "0.6.0", "expected baseline"),
    ],
)
def test_core_runtime_versions_reject_incompatible_or_mismatched_values(
    distribution, module, expected, message
):
    with pytest.raises(SystemExit, match=message):
        validate_core_runtime_versions(distribution, module, expected)


@pytest.mark.parametrize("label", ["wheel METADATA", "sdist PKG-INFO"])
def test_correct_artifact_metadata_is_accepted(label):
    validate_package_metadata(
        _package_metadata(core_requirements=("pds-core <0.7, >=0.6",)),
        "0.9.1",
        label,
    )


@pytest.mark.parametrize(
    ("metadata_text", "message"),
    [
        (_package_metadata(core_requirements=()), "exactly one pds-core"),
        (
            _package_metadata(core_requirements=("pds-core>=0.6",)),
            "exactly >=0.6,<0.7",
        ),
        (
            _package_metadata(
                core_requirements=("pds-core @ https://example.invalid/core.whl",)
            ),
            "must not use a URL",
        ),
        (
            _package_metadata(
                core_requirements=(
                    "pds-core>=0.6,<0.7; python_version < '3.12'",
                )
            ),
            "must not use an environment marker",
        ),
        (
            _package_metadata(core_requirements=("pds-core[testing]>=0.6,<0.7",)),
            "must not use extras",
        ),
        (
            _package_metadata(
                core_requirements=("pds-core>=0.6,<0.7", "pds-core>=0.6,<0.7")
            ),
            "exactly one pds-core",
        ),
        (
            _package_metadata(requires_python=None),
            "exactly one Requires-Python",
        ),
        (
            _package_metadata(requires_python=">=3.10"),
            "Requires-Python must be exactly >=3.11",
        ),
        (_package_metadata(name="another-package"), "name must be scoreform"),
        (_package_metadata(version="0.9.0"), "does not report version 0.9.1"),
    ],
)
def test_incorrect_artifact_metadata_is_rejected(metadata_text, message):
    with pytest.raises(ArtifactValidationError, match=message):
        validate_package_metadata(metadata_text, "0.9.1", "test artifact")


def test_spdx_license_syntax_has_compatible_setuptools_minimum():
    import tomllib

    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["license"] == "MIT"
    assert project["build-system"]["requires"] == ["setuptools>=77.0.0"]


def test_physical_acceptance_fixtures_have_exact_contract():
    fixture_root = Path("tests/fixtures/release")
    assignment = json.loads(
        (fixture_root / "physical_acceptance_assignment.json").read_text(
            encoding="utf-8"
        )
    )
    with (fixture_root / "physical_acceptance_roster.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        roster = list(csv.DictReader(stream))

    assert assignment["assignment_id"] == "physical_acceptance_30"
    assert assignment["layout_id"] == "standard_15q_abcd_v1"
    assert assignment["question_count"] == 30
    assert roster == [
        {
            "class_id": "physical_acceptance",
            "student_id": "synthetic1",
            "last_name": "Synthetic",
            "first_name": "Student",
            "period": "1",
        }
    ]
    marked_answers = dict(assignment["answer_key"])
    marked_answers["5"] = "B"
    marked_answers["20"] = "A"
    marked_answers["30"] = ""
    assert sum(
        marked_answers[str(number)] == assignment["answer_key"][str(number)]
        for number in range(1, 31)
    ) == 27
