from repo_investigator.cleaning.clean_commits import extract_closed_issue_numbers


def test_recognizes_standard_closing_keywords():
    assert extract_closed_issue_numbers("fixes #42: crash on startup") == [42]
    assert extract_closed_issue_numbers("Closes: #100") == [100]
    assert extract_closed_issue_numbers("resolved #7") == [7]


def test_does_not_match_bare_mention_without_closing_verb():
    # A bare "#42" reference doesn't mean this commit closes it -- e.g.
    # "see #42 for context" should not be treated as a bug-fix link.
    assert extract_closed_issue_numbers("see #42 for context, adds feature") == []


def test_handles_multiple_references_in_one_message():
    assert extract_closed_issue_numbers("fixes #1 and closes #2") == [1, 2]


def test_handles_empty_or_none_message():
    assert extract_closed_issue_numbers("") == []
    assert extract_closed_issue_numbers(None) == []


def test_case_insensitive():
    assert extract_closed_issue_numbers("FIXES #5") == [5]
    assert extract_closed_issue_numbers("Fix #6") == [6]
