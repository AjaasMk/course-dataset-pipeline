from src.extract.segment_match import UNCLASSIFIED, SEGMENT_ALIASES, classify_heading
from src.retrieve.models import Segment


def test_every_segment_has_an_alias_entry():
    assert set(SEGMENT_ALIASES) == set(Segment)


def test_a_clear_curriculum_heading_classifies_correctly():
    segment, score = classify_heading("COURSE OBJECTIVE(S):")
    assert segment is Segment.CURRICULUM
    assert score >= 0.80


def test_a_clear_ranking_heading_classifies_correctly():
    segment, score = classify_heading("India Rankings 2025: Engineering")
    assert segment is Segment.RANKING_ACCREDITATION
    assert score >= 0.80


def test_a_person_name_heading_is_unclassified():
    # Real ALL-CAPS-heading false positive from the AICTE PDF: a faculty
    # reference credit, not a real section title.
    segment, _ = classify_heading("PROF.  MANOJ HARBOLA IIT KANPUR")
    assert segment is UNCLASSIFIED


def test_generic_front_matter_is_unclassified():
    for heading in ["PREAMBLE", "PREFACE", "MESSAGE"]:
        segment, _ = classify_heading(heading)
        assert segment is UNCLASSIFIED, f"{heading!r} should not force-match a segment"


def test_navigation_chrome_is_unclassified():
    for heading in ["Helpdesk", "Additional Links", "LATEST NEWS", "Candidate Activity"]:
        segment, _ = classify_heading(heading)
        assert segment is UNCLASSIFIED, f"{heading!r} should not force-match a segment"


def test_unclassified_still_reports_its_best_score():
    # The raw heading and its near-miss score are what let a future alias
    # table expansion be evidence-driven -- not just a dropped flag.
    _, score = classify_heading("PREAMBLE")
    assert 0.0 <= score < 1.0
