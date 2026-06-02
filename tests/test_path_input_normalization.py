from scoreform.workflows import normalize_path_input


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
