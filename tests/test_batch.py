from src.retrieve import batch
from src.schema import SourceType


def test_normalize_strips_trailing_parenthetical():
    assert batch.normalize_course_name("Allopathic Medicine & Surgery (Core)") == "Allopathic Medicine & Surgery"


def test_normalize_strips_trailing_parenthetical_with_slash_inside():
    assert batch.normalize_course_name("Law (Core / Professional)") == "Law"


def test_normalize_takes_segment_before_slash_after_stripping_parens():
    assert batch.normalize_course_name("Business Administration / Management (Core)") == "Business Administration"


def test_normalize_takes_segment_before_slash_with_no_trailing_parens():
    assert batch.normalize_course_name("Physiotherapy / Physical Therapy") == "Physiotherapy"


def test_normalize_leaves_clean_name_unchanged():
    assert batch.normalize_course_name("Mechanical Engineering") == "Mechanical Engineering"


def test_infer_source_category_for_regulator_pdf():
    assert batch.infer_source_category(SourceType.REGULATOR_PDF) == "regulatory_primary"


def test_infer_source_category_for_regulator_webpage():
    assert batch.infer_source_category(SourceType.REGULATOR_WEBPAGE) == "regulatory_primary"


def test_infer_source_category_for_aggregator_webpage():
    assert batch.infer_source_category(SourceType.AGGREGATOR_WEBPAGE) == "fact_supplement_independent_writing_required"


def test_infer_source_category_falls_back_to_unknown():
    assert batch.infer_source_category(SourceType.NONE) == "unknown"


def test_course_result_matched_round_trips_through_json():
    result = batch.CourseResult(
        raw_name="Mechanical Engineering",
        course_name="Mechanical Engineering",
        category="engineering",
        tier_group="strong_tier",
        outcome="matched",
        source_category="fact_supplement_independent_writing_required",
    )
    restored = batch.CourseResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_batch_report_round_trips_through_json():
    report = batch.BatchReport(
        results=[
            batch.CourseResult(
                raw_name="Mechanical Engineering",
                course_name="Mechanical Engineering",
                category="engineering",
                tier_group="strong_tier",
                outcome="matched",
                source_category="fact_supplement_independent_writing_required",
            ),
        ],
        summary_by_tier={
            "strong_tier": batch.TierSummary(
                matched_by_source={"fact_supplement_independent_writing_required": 1},
                no_source_found=0,
                errored=0,
            ),
        },
    )
    restored = batch.BatchReport.model_validate_json(report.model_dump_json())
    assert restored == report
