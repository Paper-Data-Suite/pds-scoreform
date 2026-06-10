from pathlib import Path

from scoreform import workflows
from scoreform.workflows import (
    discover_scans_in_inbox,
    is_supported_scan_file,
    normalize_path_input,
)


def test_normalize_path_input_strips_matching_surrounding_quotes():
    assert normalize_path_input('"file.pdf"') == "file.pdf"
    assert normalize_path_input("'file.pdf'") == "file.pdf"
    assert normalize_path_input(' "file with spaces.pdf" ') == "file with spaces.pdf"


def test_normalize_path_input_strips_whitespace_without_quotes():
    assert normalize_path_input(" file.pdf ") == "file.pdf"


def test_normalize_path_input_preserves_unmatched_quotes():
    assert normalize_path_input('"unterminated.pdf') == '"unterminated.pdf'
    assert normalize_path_input('unterminated.pdf"') == 'unterminated.pdf"'


def test_normalize_path_input_preserves_internal_quotes():
    assert normalize_path_input('file"inner".pdf') == 'file"inner".pdf'


def test_is_supported_scan_file_accepts_pdf_and_images():
    assert is_supported_scan_file("scan.pdf")
    assert is_supported_scan_file("scan.PNG")
    assert is_supported_scan_file("scan.jpeg")
    assert is_supported_scan_file("scan.tif")


def test_is_supported_scan_file_rejects_unsupported_and_hidden_files():
    assert not is_supported_scan_file("notes.txt")
    assert not is_supported_scan_file("results.csv")
    assert not is_supported_scan_file(".hidden.pdf")


def test_discover_scans_in_inbox_returns_supported_files_sorted(tmp_path):
    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    for filename in [
        "mixed_scan.pdf",
        "notes.txt",
        "class_packet_period2.PDF",
        "makeup_scan_2026_06_04.jpg",
        ".hidden.png",
    ]:
        (scans_dir / filename).write_text("synthetic", encoding="utf-8")
    (scans_dir / "nested.png").mkdir()

    assert discover_scans_in_inbox(scans_dir) == [
        str(scans_dir / "class_packet_period2.PDF"),
        str(scans_dir / "makeup_scan_2026_06_04.jpg"),
        str(scans_dir / "mixed_scan.pdf"),
    ]


def test_discover_scans_in_inbox_returns_empty_for_missing_or_empty_dir(tmp_path):
    assert discover_scans_in_inbox(tmp_path / "missing_scans_inbox") == []

    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    (scans_dir / "notes.txt").write_text("not a scan", encoding="utf-8")

    assert discover_scans_in_inbox(scans_dir) == []


def test_discover_scans_in_inbox_uses_core_route_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    route_calls = []
    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    scan_path = scans_dir / "scan.pdf"
    scan_path.write_text("synthetic", encoding="utf-8")

    monkeypatch.setattr(
        workflows,
        "scans_inbox_dir",
        lambda root: route_calls.append(root) or Path(root) / "scans_inbox",
    )

    assert discover_scans_in_inbox() == [str(Path("scans_inbox") / "scan.pdf")]
    assert route_calls == ["."]
    assert scan_path.exists()
