import pytest

from src.courses.taxonomy import Course
from src.retrieve.models import RETRIEVAL_SEGMENTS, IntentRole, Segment, SourceTier
from src.retrieve.planner import SEGMENT_FIELD_IDS, plan_course
from src.retrieve.registry import load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def _course(**overrides) -> Course:
    fields = {
        "course_id": "mechanical_engineering",
        "standard_course_name": "Mechanical Engineering",
        "fields": ["Engineering & Applied Technolog"],
        "aliases": ["B.Tech Mechanical Engineering", "B.E. Mechanical"],
    }
    fields.update(overrides)
    return Course(**fields)


def test_every_retrieval_segment_has_a_field_id_range():
    assert set(SEGMENT_FIELD_IDS) == set(RETRIEVAL_SEGMENTS)


def test_field_ids_are_unique_across_segments():
    seen = [f for ids in SEGMENT_FIELD_IDS.values() for f in ids]
    assert len(seen) == len(set(seen))


def test_planning_emits_intents_for_a_course(registry):
    assert plan_course(_course(), registry)


def test_intents_carry_no_document_url(registry):
    for intent in plan_course(_course(), registry):
        assert not hasattr(intent, "document_url")


def test_intent_field_ids_match_its_segment(registry):
    for intent in plan_course(_course(), registry):
        assert set(intent.field_ids) <= set(SEGMENT_FIELD_IDS[intent.segment])


def test_query_terms_include_the_course_name_and_its_aliases(registry):
    intent = plan_course(_course(), registry)[0]
    assert "Mechanical Engineering" in intent.query_terms


def test_entrance_intents_against_exam_sources_include_exam_vocabulary(registry):
    # NTA/CUET publish per-EXAM pages (Joint Entrance Examination, NEET,
    # CUET-UG), not per-COURSE pages -- fuzzy-matching a course name alone
    # against an exam title structurally caps out around 0.4-0.5, confirmed
    # live against the real NTA index for "Physics (Core)" (best: 0.50 vs
    # "Joint Entrance Examination"). Course-name terms alone are kept (other
    # candidates might still be a real course-name match some day), but for
    # engineering specifically the union must also carry the bare acronym
    # "JEE" -- not the full title, which collides with "Hotel Management
    # Joint Entrance Examination" under token_set_ratio (confirmed live,
    # see src/retrieve/planner.py and tests/test_nta.py).
    engineering = _course(fields=["Engineering & Applied Technolog"])
    intents = plan_course(engineering, registry)
    nta_entrance = [
        i for i in intents if i.segment == Segment.ENTRANCE_ADMISSION and i.source_id == "NTA"
    ]
    assert nta_entrance
    for intent in nta_entrance:
        assert "JEE" in intent.query_terms
        assert "Joint Entrance Examination" not in intent.query_terms
        assert "Mechanical Engineering" in intent.query_terms  # course-name terms still present


def test_entrance_intents_for_medicine_include_neet_vocabulary(registry):
    medicine = _course(
        course_id="mbbs", standard_course_name="MBBS", fields=["Medicine, Dentistry & Clinical "],
        aliases=[],
    )
    intents = plan_course(medicine, registry)
    nta_entrance = [
        i for i in intents if i.segment == Segment.ENTRANCE_ADMISSION and i.source_id == "NTA"
    ]
    assert nta_entrance
    for intent in nta_entrance:
        assert "NEET" in intent.query_terms


def test_exam_vocabulary_is_not_added_outside_entrance_admission(registry):
    # Adding exam terms to, say, Eligibility/UGC query_terms would just be
    # noise -- scoped to the one segment and the two exam-organized sources
    # (NTA, CUET) it actually fixes.
    engineering = _course(fields=["Engineering & Applied Technolog"])
    for intent in plan_course(engineering, registry):
        exam_scoped = intent.segment == Segment.ENTRANCE_ADMISSION and intent.source_id in {"NTA", "CUET"}
        if not exam_scoped:
            assert "JEE" not in intent.query_terms


def test_tier_d_sources_are_only_ever_planned_as_discovery(registry):
    for intent in plan_course(_course(), registry):
        if all(t in (SourceTier.D, SourceTier.E, SourceTier.F) for t in registry.tiers_for(intent.source_id)):
            assert intent.role is IntentRole.DISCOVERY


def test_every_planned_intent_passes_registry_validation(registry):
    for intent in plan_course(_course(), registry):
        registry.validate_intent(intent)


def test_a_source_below_the_segment_floor_is_not_planned_as_primary(registry):
    # Ranking & Accreditation requires Tier A. A Tier B or C source may still
    # corroborate, but must not hold the primary role for that segment.
    for intent in plan_course(_course(), registry):
        if intent.segment is Segment.RANKING_ACCREDITATION and intent.role is IntentRole.PRIMARY:
            assert SourceTier.A in registry.tiers_for(intent.source_id)


def test_unusable_sources_are_not_planned(registry):
    # Planning an intent against a blocked source only manufactures a failure.
    usable = {"verified", "reachable"}
    for intent in plan_course(_course(), registry):
        assert registry.sources[intent.source_id].status in usable


def test_an_engineering_course_is_not_planned_against_health_regulators(registry):
    # segment_sources lists every regulator that can serve Eligibility; the
    # Regulator Map decides which of them govern THIS course area. Without that
    # intersection a mechanical engineering course queries the Dental Council.
    planned = {i.source_id for i in plan_course(_course(), registry)}
    assert not planned & {"DCI", "INC", "PCI", "RCI", "NMC"}


def test_an_engineering_course_is_still_planned_against_aicte(registry):
    planned = {i.source_id for i in plan_course(_course(), registry)}
    assert "AICTE" in planned


def test_a_medical_course_is_planned_against_its_own_regulators(registry):
    medicine = _course(
        course_id="allopathic_medicine",
        standard_course_name="Allopathic Medicine & Surgery (Core)",
        fields=["Medicine, Dentistry & Clinical "],
    )
    planned = {i.source_id for i in plan_course(medicine, registry)}
    assert "NMC" in planned
    assert "AICTE" not in planned


def test_a_law_course_reaches_no_technical_regulator(registry):
    law = _course(
        course_id="criminal_law",
        standard_course_name="Criminal Law",
        fields=["Law, Governance & Public Policy"],
    )
    planned = {i.source_id for i in plan_course(law, registry)}
    assert not planned & {"AICTE", "NMC", "DCI", "PCI"}


def test_non_regulator_sources_are_unaffected_by_the_regulator_map(registry):
    # NIRF, NTA and NSP serve every course area; only regulators are filtered.
    planned = {i.source_id for i in plan_course(_course(), registry)}
    assert {"NIRF", "NTA", "NSP"} <= planned


def test_intent_ids_are_unique_within_a_course(registry):
    intents = plan_course(_course(), registry)
    assert len({i.intent_id for i in intents}) == len(intents)


def test_intent_id_is_stable_across_replans_regardless_of_segment_order(registry):
    # intent_id must be derived from (course, segment, source) content, not
    # from iteration position -- RETRIEVAL_SEGMENTS is a frozenset, and its
    # iteration order is randomized per Python process (PYTHONHASHSEED),
    # confirmed live (3 different orderings across 3 fresh processes). A
    # counter-based id lets the SAME id string mean a different (segment,
    # source) pair on every re-run, which -- combined with INSERT OR REPLACE
    # in store.py keyed only on intent_id -- silently aliases an old run's
    # resolved document onto a completely different intent on the next run.
    # This test would not have caught the old counter-based scheme, since
    # within a single process the order is internally consistent; it asserts
    # the actual fix: the id is computable from content alone, without
    # planning the whole course first.
    intents = plan_course(_course(), registry)
    for intent in intents:
        assert intent.intent_id == f"RI-{intent.course_id}-{intent.segment.value}-{intent.source_id}"


def test_intent_id_has_no_bare_counter_suffix(registry):
    intents = plan_course(_course(), registry)
    for intent in intents:
        assert not intent.intent_id.rsplit("-", 1)[-1].isdigit()


def test_priority_starts_at_one_within_each_segment(registry):
    by_segment: dict[Segment, list[int]] = {}
    for intent in plan_course(_course(), registry):
        by_segment.setdefault(intent.segment, []).append(intent.priority)
    for priorities in by_segment.values():
        assert min(priorities) == 1
