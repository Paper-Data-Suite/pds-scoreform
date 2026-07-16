from pathlib import Path

import pytest

import scripts.verify_text_encoding as encoding_module
from scripts.verify_text_encoding import find_mojibake, validate_text_encoding


@pytest.mark.parametrize(
    "text",
    [
        "bad \u0393\u00c7\u00f6 dash",
        "bad \u0393\u00c7\u00a3quote\u0393\u00c7\u00a5",
        "bad \u00e2\u20ac\u201d dash",
        "bad \u00ef\u00bf\u00bd replacement",
        "an actual \ufffd replacement character",
    ],
)
def test_suspicious_mojibake_sequences_are_rejected(tmp_path, monkeypatch, text):
    sample = tmp_path / "sample.md"
    sample.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        encoding_module, "tracked_text_paths", lambda _root: (sample,)
    )

    failures = validate_text_encoding(tmp_path)

    assert len(failures) == 1
    assert "mojibake sequence" in failures[0]


def test_isolated_legitimate_unicode_letters_are_accepted():
    assert find_mojibake("\u0393 \u00c7 \u00e2 \u00ef") == ()


def test_tracked_release_text_is_strict_utf8_without_mojibake():
    root = Path(__file__).resolve().parents[1]

    assert validate_text_encoding(root) == []
