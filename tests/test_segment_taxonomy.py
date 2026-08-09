from src.retrieve.models import EXPLANATORY_SEGMENTS, RETRIEVAL_SEGMENTS, Segment


def test_the_four_explanatory_segments_exist():
    names = {s.name for s in EXPLANATORY_SEGMENTS}
    assert names == {"COURSE_OVERVIEW", "SKILLS_DEVELOPED", "FURTHER_STUDY_PATHWAYS", "STUDENT_REVIEWS"}


def test_retrieval_segments_excludes_the_explanatory_four():
    assert RETRIEVAL_SEGMENTS.isdisjoint(EXPLANATORY_SEGMENTS)


def test_retrieval_segments_is_computed_not_hand_duplicated():
    # The requirement is one canonical enum with a derived subset, not two
    # independently maintained lists that could silently drift apart.
    assert RETRIEVAL_SEGMENTS == frozenset(Segment) - EXPLANATORY_SEGMENTS


def test_the_original_fourteen_retrieval_segments_are_unchanged():
    # Existing Stage 1 code (planner, config/sources.yaml, resolver reporting)
    # depends on these exact 14 values continuing to exist and mean the same
    # thing -- extending the taxonomy must not rename or drop any of them.
    original = {
        "Course Identity", "Duration & Mode", "Eligibility", "Entrance & Admission",
        "Curriculum", "Specialisation", "Institution & Offering", "Ranking & Accreditation",
        "Fees", "Scholarships", "Career Mapping", "Salary", "Recruiters & Placement",
        "Internships",
    }
    assert {s.value for s in RETRIEVAL_SEGMENTS} == original


def test_segment_has_eighteen_values_covering_nineteen_segment_sources_rows():
    # S08 (institutions offering) and S09 (ownership classification) both roll
    # into the client's own "Institution & Offering" Data Fields segment, so
    # the canonical taxonomy has 18 distinct values, not 19 -- verified
    # directly against the workbook, not assumed from the S01-S19 count.
    assert len(list(Segment)) == 18
