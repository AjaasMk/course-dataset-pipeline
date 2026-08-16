from __future__ import annotations

import copy

import pytest

from coursegen.generate import strip_citation_markers
from coursegen.validate import RuleContext, validate_document

CTX = RuleContext(currency="INR", allowed_domains=("ugc.gov.in",), search_filtered=True)


def codes(document: dict, root_schema: dict) -> set[str]:
    return {f.code for f in validate_document(document, root_schema, CTX, scope="d").errors}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Salaries extend to INR 50 lakh per year.[1][2]", "Salaries extend to INR 50 lakh per year."),
        ("not just ready-made apps[9].", "not just ready-made apps."),
        ("the base route for 4-year entry[2][3]", "the base route for 4-year entry"),
        ("Tech requirement[2] ", "Tech requirement"),
        ("depending on the institute.[1][2][10]", "depending on the institute."),
        ("markers [1, 2] with a comma", "markers with a comma"),
        ("no markers at all.", "no markers at all."),
        ("a bracket [word] is untouched", "a bracket [word] is untouched"),
    ],
)
def test_citation_markers_are_stripped(raw: str, expected: str) -> None:
    assert strip_citation_markers(raw) == expected


def test_stripper_walks_the_whole_document() -> None:
    doc = {"a": "x[1]", "b": ["y[2]", {"c": "z[3][4]"}], "n": 5, "ok": None}
    assert strip_citation_markers(doc) == {"a": "x", "b": ["y", {"c": "z"}], "n": 5, "ok": None}


@pytest.mark.parametrize(
    "note",
    [
        "Ranks and scores are arranged from the search results available in this conversation.",
        "Fees shown are total programme fees from the source snippets where available.",
        "Annualised college fee data was not consistently published in the results.",
        "Published sources show a wide spread rather than a single fixed number.",
        "Figures could not be verified for every college.",
        "Based on the search, most programmes run four years.",
    ],
)
def test_process_commentary_is_rejected(root_schema: dict, demo_document: dict, note: str) -> None:
    doc = copy.deepcopy(demo_document)
    doc["colleges"]["data_note"] = note + " " * 0 + " Additional filler to satisfy the length bound."
    assert "process_commentary" in codes(doc, root_schema)


def test_a_proper_subject_caveat_is_accepted(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["colleges"]["data_note"] = (
        "Rankings change each year and cover only institutions that took part. Check the official "
        "ranking body, the year, and whether the course is offered before shortlisting a college."
    )
    assert "process_commentary" not in codes(doc, root_schema)


def test_citation_markers_are_rejected_if_they_survive(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["overview"]["paragraphs"][0] = doc["overview"]["paragraphs"][0] + "[3]"
    assert "citation_markers" in codes(doc, root_schema)


def test_college_fee_that_is_really_a_programme_total_is_rejected(
    root_schema: dict, demo_document: dict
) -> None:
    doc = copy.deepcopy(demo_document)
    annual_max = doc["quick_facts"]["indicative_annual_fees"]["max"]
    doc["colleges"]["items"][0]["annual_fee"] = annual_max * 3
    found = [
        f
        for f in validate_document(doc, root_schema, CTX, scope="d").errors
        if f.code == "college_fee_not_annual"
    ]
    assert found
    assert "whole-programme fee" in found[0].message


def _first_of_type(document: dict, wanted: str) -> dict:
    return next(c for c in document["colleges"]["items"] if c["institution_type"] == wanted)


def test_registration_charge_at_a_private_college_is_rejected(
    root_schema: dict, demo_document: dict
) -> None:
    doc = copy.deepcopy(demo_document)
    _first_of_type(doc, "private")["annual_fee"] = 2100
    assert "college_fee_implausibly_low" in codes(doc, root_schema)


def test_a_genuinely_cheap_government_seat_is_accepted(
    root_schema: dict, demo_document: dict
) -> None:
    doc = copy.deepcopy(demo_document)
    _first_of_type(doc, "government")["annual_fee"] = 1628
    assert "college_fee_implausibly_low" not in codes(doc, root_schema)


def test_a_token_government_figure_is_still_rejected(
    root_schema: dict, demo_document: dict
) -> None:
    doc = copy.deepcopy(demo_document)
    _first_of_type(doc, "government")["annual_fee"] = 120
    assert "college_fee_implausibly_low" in codes(doc, root_schema)


def test_plausible_college_fees_still_pass(root_schema: dict, demo_document: dict) -> None:
    assert "college_fee_not_annual" not in codes(demo_document, root_schema)
    assert "college_fee_implausibly_low" not in codes(demo_document, root_schema)


def test_leak_patterns_contain_no_control_characters() -> None:
    from coursegen.validate.rules import PROCESS_LEAK_PATTERNS

    for pattern in PROCESS_LEAK_PATTERNS:
        assert all(ord(c) >= 32 for c in pattern), (
            f"{pattern!r} contains a control character — a shell-escaped \\b becomes a literal "
            "backspace and the pattern silently never matches"
        )


def test_stripper_never_emits_control_characters() -> None:
    for raw in [
        "a sentence ending here .",
        "two items , and more",
        "ends here[2] .",
        "spaced  out ; text",
        "per year.[1][2]",
    ]:
        out = strip_citation_markers(raw)
        assert all(ord(c) >= 32 or c == "\n" for c in out), (
            f"{raw!r} produced control characters {out!r} — a shell-escaped backreference "
            "becomes a literal control byte and lands in page copy"
        )


def test_punctuation_survives_marker_removal() -> None:
    assert strip_citation_markers("ends here[2] .") == "ends here."
    assert strip_citation_markers("items , and more") == "items, and more"
    assert strip_citation_markers("done[1]!") == "done!"
