from __future__ import annotations

from pathlib import Path

from scoreform.scan_review_persistence import _workspace_diagnostic_paths


def test_workspace_diagnostic_paths_rebase_inside_and_drop_unsafe(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    inside = (
        root
        / "classes"
        / "class1"
        / "modules"
        / "scoreform"
        / "debug"
        / "inside.png"
    )
    outside = tmp_path / "outside" / "private.png"
    relative = "classes/class1/modules/scoreform/debug/relative.png"

    assert _workspace_diagnostic_paths(
        (
            str(inside),
            relative,
            str(outside),
            "../escape.png",
            str(inside),
        ),
        root,
    ) == tuple(sorted({inside.relative_to(root).as_posix(), relative}))


def test_workspace_diagnostic_paths_without_root_only_accept_safe_relative() -> None:
    assert _workspace_diagnostic_paths(
        (
            "classes/class1/modules/scoreform/debug/inside.png",
            "../escape.png",
            "/absolute/private.png",
        ),
        None,
    ) == ("classes/class1/modules/scoreform/debug/inside.png",)
