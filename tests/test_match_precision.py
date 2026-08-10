import pytest

from src.retrieve.matching import BOILERPLATE_PATTERNS, TokenWeights, guarded_score

_AICTE = BOILERPLATE_PATTERNS["AICTE"]

# A miniature stand-in for AICTE's real 47-title index. It carries the same
# shape that matters: "engineering", "science" and "technology" recur across
# many titles and separate nothing, while "biotechnology", "robotics" and
# "animation" each pick out one document -- and "naval", "mass" and "food"
# never appear at all, which is what makes their absence decisive.
_TITLES = [
    "Revised Model Curriculum for UG Degree Course in Mechanical Engineering",
    "Revised Model Curriculum for UG Degree Course in Electronics and Communication Engineering",
    "Model Curriculum for UG Degree Course in Computer Science and Engineering(Engineering and Technology)",
    "AICTE Model Curriculum UG Degree in Robotics & Artificial Intelligence Engineering",
    "AICTE Model Curriculum UG Degree in Chemical Engineering",
    "AICTE Model Curriculum UG Degree in Textile Engineering",
    "Model Curriculum for UG Degree Course in Biotechnology",
    "Model Curriculum for Bachelor of Architecture(B.Arch)-2019",
    "Model Curriculum for Diploma Course in Animation",
    "Model Curriculum for Diploma Course in Game Design",
    "Model Curriculum for Diploma Course in Digital Marketing",
]


@pytest.fixture
def weights():
    return TokenWeights(_TITLES, _AICTE)


def _score(term, title, weights):
    return guarded_score(term, title, _AICTE, weights)


@pytest.mark.parametrize(
    "term,title",
    [
        # Every one of these was a real false positive scoring 0.80-1.00 under
        # plain token_set_ratio, on a shared COMMON word while the query's own
        # distinctive word was absent from the title.
        (
            "Mass Communication",
            "Revised Model Curriculum for UG Degree Course in Electronics and Communication Engineering",
        ),
        ("Naval Architecture", "Model Curriculum for Bachelor of Architecture(B.Arch)-2019"),
        (
            "Food Science & Technology",
            "Model Curriculum for UG Degree Course in Computer Science and Engineering(Engineering and Technology)",
        ),
    ],
)
def test_a_shared_common_word_cannot_carry_a_match(term, title, weights):
    assert _score(term, title, weights) < 0.80


@pytest.mark.parametrize(
    "term,title",
    [
        ("Biotechnology", "Model Curriculum for UG Degree Course in Biotechnology"),
        ("Mechanical Engineering", "Revised Model Curriculum for UG Degree Course in Mechanical Engineering"),
        ("Textile Engineering", "AICTE Model Curriculum UG Degree in Textile Engineering"),
        ("Game Design", "Model Curriculum for Diploma Course in Game Design"),
    ],
)
def test_an_exact_subject_match_keeps_its_full_score(term, title, weights):
    assert _score(term, title, weights) >= 0.95


@pytest.mark.parametrize(
    "term,title",
    [
        (
            "Computer Engineering",
            "Model Curriculum for UG Degree Course in Computer Science and Engineering(Engineering and Technology)",
        ),
        (
            "Robotics Engineering",
            "AICTE Model Curriculum UG Degree in Robotics & Artificial Intelligence Engineering",
        ),
    ],
)
def test_a_course_matching_a_broader_document_survives(term, title, weights):
    # These are the bindings an earlier candidate-side guard destroyed: every
    # distinctive word of the course name is present, the document simply
    # covers more ground.
    assert _score(term, title, weights) >= 0.80


def test_a_bracketed_specialisation_marker_does_not_cost_the_subject_its_document(weights):
    # "Animation (Design/Art Track)" scored 0.27 against the real Animation
    # diploma when the bracketed words were weighed as distinctive. They
    # qualify the subject; they do not identify it.
    score = _score("Animation (Design/Art Track)", "Model Curriculum for Diploma Course in Animation", weights)

    assert score >= 0.80


def test_an_unmatched_common_word_costs_almost_nothing(weights):
    # "Engineering" recurs across the corpus, so Chemical Engineering must not
    # be punished for the title omitting nothing it needs.
    assert _score("Chemical Engineering", "AICTE Model Curriculum UG Degree in Chemical Engineering", weights) >= 0.95


def test_boilerplate_alone_cannot_carry_a_match(weights):
    assert _score("Model Curriculum Course", "AICTE Model Curriculum UG Degree in Textile Engineering", weights) < 0.80


def test_score_is_zero_when_the_candidate_has_no_content_left(weights):
    assert _score("Biotechnology", "Model Curriculum for UG Degree Course in", weights) == 0.0


def test_without_weights_it_degrades_to_plain_similarity():
    # Lets adapters adopt the guard one at a time rather than all at once.
    assert guarded_score("Biotechnology", "Biotechnology") >= 0.95


def test_a_word_absent_from_the_corpus_outweighs_one_that_recurs(weights):
    # The property the whole guard rests on, asserted directly rather than
    # only through its effects.
    assert weights.weight("naval") > weights.weight("engineering")
    assert weights.weight("mass") > weights.weight("communication")


def test_a_general_subject_still_takes_a_narrower_specialisation_known_residual(weights):
    # Documented limit, not a fix: every distinctive word of "Marketing" does
    # appear in "Digital Marketing", so it survives -- structurally identical
    # to Computer Engineering matching Computer Science and Engineering, which
    # we want. Separating them needs domain knowledge this scorer lacks.
    assert _score("Marketing", "Model Curriculum for Diploma Course in Digital Marketing", weights) >= 0.80
