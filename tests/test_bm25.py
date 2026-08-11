import pytest

from src.extract.bm25 import BM25, tokenise
from src.extract.segment_queries import NoQueryForSegment, query_for

CORPUS = [
    "Semester 3 core subjects Thermodynamics Fluid Mechanics credits 4",
    "Acknowledgements the committee thanks the chairman and members",
    "List of electives Robotics Automation credits 3 semester 6",
]


def test_ranking_puts_the_matching_document_first():
    ranked = BM25(CORPUS).rank("core subjects credits semester")
    assert ranked[0][0] in (0, 2)
    assert ranked[-1][0] == 1


def test_a_term_in_every_document_cannot_decide_the_ranking():
    # IDF must come from the corpus. "credits" appears in two of three, so it
    # separates less than "electives", which appears in one.
    bm25 = BM25(CORPUS)
    assert bm25.idf["electives"] > bm25.idf["credits"]


def test_ties_break_on_original_order_so_runs_are_reproducible():
    bm25 = BM25(["alpha beta", "alpha beta"])
    assert [i for i, _ in bm25.rank("alpha")] == [0, 1]


def test_a_query_with_no_corpus_term_scores_everything_zero():
    assert all(score == 0.0 for _, score in BM25(CORPUS).rank("zzzz"))


def test_top_k_limits_the_result():
    assert len(BM25(CORPUS).rank("credits", top_k=2)) == 2


def test_short_tokens_are_dropped():
    assert "of" not in tokenise("list of electives")


def test_empty_corpus_does_not_divide_by_zero():
    assert BM25([]).rank("anything") == []


def test_a_segment_without_a_query_raises_rather_than_defaulting():
    # A silent generic query would retrieve arbitrary chunks and look like it
    # worked -- worse than refusing.
    with pytest.raises(NoQueryForSegment):
        query_for("Student Reviews & Campus Experience")


def test_curriculum_query_carries_the_keep_list_vocabulary():
    query = query_for("Curriculum")
    for term in ("core subjects", "credits", "semester", "elective", "outcomes"):
        assert term in query
