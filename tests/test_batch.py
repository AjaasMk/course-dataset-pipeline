import logging
from unittest.mock import patch

from src.retrieve import batch
from src.retrieve.base import SourceMatch
from src.schema import ManifestEntry, SourceCategory, SourceType


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


def test_infer_source_category_for_general_background_webpage():
    assert batch.infer_source_category(SourceType.GENERAL_BACKGROUND_WEBPAGE) == "general_background"


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


class _ScriptedAdapter:
    def __init__(self, match_result=None, download_result=None, raise_on_match=None):
        self._match_result = match_result
        self._download_result = download_result
        self._raise_on_match = raise_on_match
        self.match_calls = []

    def build_index(self):
        return {}

    def match(self, course_name, index):
        self.match_calls.append(course_name)
        if self._raise_on_match is not None:
            raise self._raise_on_match
        return self._match_result

    def download(self, match, tier):
        return self._download_result


def _manifest_entry(source_type=SourceType.AGGREGATOR_WEBPAGE):
    return ManifestEntry(
        course_name="X",
        tier="engineering",
        source_type=source_type,
        matched_url="https://example.com/x",
        match_confidence=0.95,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )


def _match(confidence=0.95):
    return SourceMatch(course_name="X", matched_name="X", matched_url="https://example.com/x", confidence=confidence)


def _fixture_env(adapter):
    categories = {"engineering": "strong_tier"}
    retrieval_order = {"strong_tier": ["fact_supplement_independent_writing_required"]}
    registry = {SourceCategory.FACT_SUPPLEMENT_INDEPENDENT_WRITING_REQUIRED: {"*": adapter}}
    indices = {adapter: {}}
    return categories, retrieval_order, registry, indices


def test_run_batch_resolves_tier_group_via_categories_map():
    adapter = _ScriptedAdapter(match_result=_match(), download_result=_manifest_entry())
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [{"raw_name": "Mechanical Engineering", "category": "engineering"}]

    report = batch.run_batch(
        courses=courses,
        categories=categories,
        retrieval_order=retrieval_order,
        indices=indices,
        registry=registry,
        threshold=0.8,
        delay_seconds=0,
    )

    assert report.results[0].tier_group == "strong_tier"


def test_run_batch_records_matched_outcome_with_inferred_source_category():
    adapter = _ScriptedAdapter(
        match_result=_match(),
        download_result=_manifest_entry(source_type=SourceType.AGGREGATOR_WEBPAGE),
    )
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [{"raw_name": "Mechanical Engineering", "category": "engineering"}]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    result = report.results[0]
    assert result.outcome == "matched"
    assert result.source_category == "fact_supplement_independent_writing_required"
    assert result.course_name == "Mechanical Engineering"  # already clean, unchanged by normalize


def test_run_batch_records_no_source_found_when_nothing_clears_threshold():
    adapter = _ScriptedAdapter(match_result=_match(confidence=0.1))
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [{"raw_name": "Nonexistent Course", "category": "engineering"}]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    assert report.results[0].outcome == "no_source_found"
    assert report.results[0].source_category is None


def test_run_batch_records_errored_outcome_and_continues_to_next_course():
    failing_adapter = _ScriptedAdapter(raise_on_match=RuntimeError("simulated network failure"))
    categories, retrieval_order, registry, indices = _fixture_env(failing_adapter)
    courses = [
        {"raw_name": "Course One", "category": "engineering"},
        {"raw_name": "Course Two", "category": "engineering"},
    ]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    assert len(report.results) == 2
    assert report.results[0].outcome == "errored"
    assert "simulated network failure" in report.results[0].error
    assert report.results[1].outcome == "errored"  # same failing adapter, but the loop reached it
    assert len(failing_adapter.match_calls) == 2  # both courses were attempted


def test_run_batch_logs_errored_course(caplog):
    failing_adapter = _ScriptedAdapter(raise_on_match=RuntimeError("boom"))
    categories, retrieval_order, registry, indices = _fixture_env(failing_adapter)
    courses = [{"raw_name": "Course One", "category": "engineering"}]

    with caplog.at_level(logging.INFO):
        batch.run_batch(
            courses=courses, categories=categories, retrieval_order=retrieval_order,
            indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
        )

    assert any("errored" in record.message for record in caplog.records)


def test_run_batch_sleeps_between_courses():
    adapter = _ScriptedAdapter(match_result=_match(), download_result=_manifest_entry())
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [
        {"raw_name": "Course One", "category": "engineering"},
        {"raw_name": "Course Two", "category": "engineering"},
    ]

    with patch("src.retrieve.batch.time.sleep") as mock_sleep:
        batch.run_batch(
            courses=courses, categories=categories, retrieval_order=retrieval_order,
            indices=indices, registry=registry, threshold=0.8, delay_seconds=2.5,
        )

    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(2.5)


def test_summary_by_tier_aggregates_matched_no_source_found_and_errored():
    adapter = _ScriptedAdapter(match_result=_match(), download_result=_manifest_entry())
    categories, retrieval_order, registry, indices = _fixture_env(adapter)
    courses = [
        {"raw_name": "Matched Course", "category": "engineering"},
    ]

    report = batch.run_batch(
        courses=courses, categories=categories, retrieval_order=retrieval_order,
        indices=indices, registry=registry, threshold=0.8, delay_seconds=0,
    )

    tier_summary = report.summary_by_tier["strong_tier"]
    assert tier_summary.matched_by_source == {"fact_supplement_independent_writing_required": 1}
    assert tier_summary.no_source_found == 0
    assert tier_summary.errored == 0
