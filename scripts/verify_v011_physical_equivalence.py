"""Bounded #195 physical-evidence bridge for ScoreForm v0.11.0.

This verifier proves runtime/package equivalence only. It never claims that a
physical printer/scanner test occurred and never makes the project-owner
carry-forward decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

BASELINE_VERSION = "0.10.0"
RELEASE_VERSION = "0.11.0"
BASELINE_WHEEL_SHA256 = (
    "13780dfff55428394baaab5deab76e340ae969fe7f96cb461ccc092df7e5679b"
)


class EquivalenceError(RuntimeError):
    """Raised when the release wheel is not a metadata-only bridge."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _single_member(names: list[str], suffix: str, label: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise EquivalenceError(
            f"{label} must contain exactly one {suffix}; found {len(matches)}"
        )
    return matches[0]


def _metadata(archive: zipfile.ZipFile, label: str) -> Message:
    names = archive.namelist()
    member = _single_member(names, ".dist-info/METADATA", label)
    return BytesParser(policy=policy.default).parsebytes(archive.read(member))


def _metadata_values(message: Message, field: str) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in message.get_all(field, []))


def _runtime_members(archive: zipfile.ZipFile) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name in archive.namelist():
        normalized = name.replace("\\", "/")
        if normalized.startswith("scoreform/") and not normalized.endswith("/"):
            result[normalized] = archive.read(name)
    return result


def verify_equivalence(
    baseline_wheel: Path,
    release_wheel: Path,
    *,
    expected_baseline_sha256: str = BASELINE_WHEEL_SHA256,
    baseline_version: str = BASELINE_VERSION,
    release_version: str = RELEASE_VERSION,
) -> dict[str, object]:
    baseline_hash = _sha256(baseline_wheel)
    if baseline_hash != expected_baseline_sha256.lower():
        raise EquivalenceError(
            "baseline wheel SHA-256 does not match the exact #195 physical candidate"
        )

    with zipfile.ZipFile(baseline_wheel) as baseline, zipfile.ZipFile(
        release_wheel
    ) as release:
        baseline_runtime = _runtime_members(baseline)
        release_runtime = _runtime_members(release)
        if baseline_runtime.keys() != release_runtime.keys():
            missing = sorted(baseline_runtime.keys() - release_runtime.keys())
            added = sorted(release_runtime.keys() - baseline_runtime.keys())
            raise EquivalenceError(
                f"runtime member set changed; missing={missing!r}; added={added!r}"
            )

        changed_runtime = [
            name
            for name in sorted(baseline_runtime)
            if baseline_runtime[name] != release_runtime[name]
        ]
        if changed_runtime:
            raise EquivalenceError(
                "ScoreForm runtime payload changed: " + ", ".join(changed_runtime)
            )

        baseline_meta = _metadata(baseline, "baseline wheel")
        release_meta = _metadata(release, "release wheel")

        if str(baseline_meta["Name"]).strip().lower() != "scoreform":
            raise EquivalenceError("baseline distribution name is not scoreform")
        if str(release_meta["Name"]).strip().lower() != "scoreform":
            raise EquivalenceError("release distribution name is not scoreform")
        if str(baseline_meta["Version"]).strip() != baseline_version:
            raise EquivalenceError("baseline metadata version mismatch")
        if str(release_meta["Version"]).strip() != release_version:
            raise EquivalenceError("release metadata version mismatch")

        for field in ("Requires-Python", "Requires-Dist"):
            if _metadata_values(baseline_meta, field) != _metadata_values(
                release_meta, field
            ):
                raise EquivalenceError(f"runtime metadata changed: {field}")

        baseline_entry = _single_member(
            baseline.namelist(), ".dist-info/entry_points.txt", "baseline wheel"
        )
        release_entry = _single_member(
            release.namelist(), ".dist-info/entry_points.txt", "release wheel"
        )
        if baseline.read(baseline_entry).replace(b"\r\n", b"\n") != release.read(
            release_entry
        ).replace(b"\r\n", b"\n"):
            raise EquivalenceError("installed entry-point metadata changed")

        baseline_top = _single_member(
            baseline.namelist(), ".dist-info/top_level.txt", "baseline wheel"
        )
        release_top = _single_member(
            release.namelist(), ".dist-info/top_level.txt", "release wheel"
        )
        if baseline.read(baseline_top) != release.read(release_top):
            raise EquivalenceError("top-level package metadata changed")

    return {
        "baseline_version": baseline_version,
        "release_version": release_version,
        "baseline_wheel_sha256": baseline_hash,
        "release_wheel_sha256": _sha256(release_wheel),
        "runtime_payload_equivalent": True,
        "runtime_member_count": len(baseline_runtime),
        "entry_points_equivalent": True,
        "requires_python_equivalent": True,
        "requires_dist_equivalent": True,
        "physical_acceptance": "not_claimed",
        "owner_carry_forward_required": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-wheel", type=Path, required=True)
    parser.add_argument("--release-wheel", type=Path, required=True)
    parser.add_argument(
        "--expected-baseline-sha256",
        default=BASELINE_WHEEL_SHA256,
    )
    args = parser.parse_args()

    try:
        result = verify_equivalence(
            args.baseline_wheel,
            args.release_wheel,
            expected_baseline_sha256=args.expected_baseline_sha256,
        )
    except (OSError, zipfile.BadZipFile, EquivalenceError) as error:
        print(f"ScoreForm v0.11.0 physical-evidence bridge failed: {error}")
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
