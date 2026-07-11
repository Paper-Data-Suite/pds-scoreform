from datetime import datetime, timezone

from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)

from scoreform import cli, cli_scan_review, menu_scan_review


def _failure(root, failure_id="failure_cli"):
    retained = root / "scans/source/2026-07-11/packet.pdf"
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_bytes(b"scan")
    return write_routing_failure_metadata(
        root,
        RoutingFailureMetadata(
            schema_version="1",
            failure_id=failure_id,
            scope="page",
            stage="scoreform_qr_review",
            created_at=datetime(2026, 7, 11, tzinfo=timezone.utc).isoformat(),
            failure_category="payload_missing",
            failure_message="missing QR code",
            source_filename="packet.pdf",
            module_details={"scoreform_failure_category": "missing_qr"},
            module="scoreform",
            retained_source_path="scans/source/2026-07-11/packet.pdf",
            source_page_number=1,
        ),
    )


def test_direct_list_and_defer_commands(tmp_path, monkeypatch, capsys):
    _failure(tmp_path)
    monkeypatch.setattr(
        cli_scan_review.workspace, "get_scoreform_workspace_root", lambda: tmp_path
    )

    assert cli.main(["list-scan-review"], default_to_menu=False) == 0
    output = capsys.readouterr().out
    assert "failure_cli" in output
    assert "Status: unresolved" in output
    assert "Retained source: scans/source/" in output

    assert (
        cli.main(
            ["resolve-scan-review", "failure_cli", "--action", "defer"],
            default_to_menu=False,
        )
        == 0
    )
    assert "deferred" in capsys.readouterr().out

    assert cli.main(["list-scan-review"], default_to_menu=False) == 0
    assert "Status: deferred" in capsys.readouterr().out


def test_direct_manual_entry_points_to_menu(tmp_path, monkeypatch, capsys):
    _failure(tmp_path)
    monkeypatch.setattr(
        cli_scan_review.workspace, "get_scoreform_workspace_root", lambda: tmp_path
    )
    assert (
        cli.main(
            [
                "resolve-scan-review",
                "failure_cli",
                "--action",
                "manual_entry",
            ],
            default_to_menu=False,
        )
        == 1
    )
    assert "Assignment Management > Resolve Scan Review Items" in capsys.readouterr().out


def test_interactive_menu_defers_item_and_returns_to_active_list(
    tmp_path, monkeypatch, capsys
):
    _failure(tmp_path)
    monkeypatch.setattr(
        menu_scan_review.workspace, "get_scoreform_workspace_root", lambda: tmp_path
    )
    monkeypatch.setattr(menu_scan_review, "clear_screen", lambda: print("<CLEAR>"))
    monkeypatch.setattr(menu_scan_review, "pause_for_user", lambda: None)
    responses = iter(["1", "9", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert menu_scan_review.launch_scan_review_menu() == 0
    output = capsys.readouterr().out.lower()
    assert output.count("<clear>") >= 4
    assert "status: deferred" in output
    assert "deferred: payload_missing" in output
    assert "{\"" not in output
