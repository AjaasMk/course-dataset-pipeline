from __future__ import annotations

import copy

import pytest

from coursegen.validate import RuleContext, validate_document

CTX = RuleContext(currency="INR", allowed_domains=("ugc.gov.in", "nirfindia.org", "nta.nic.in"))
CTX_NO_DOMAINS = RuleContext(currency="INR", allowed_domains=())


def report_for(document: dict, root_schema: dict, context: RuleContext = CTX):
    return validate_document(document, root_schema, context, scope="document")


def codes(report) -> set[str]:
    return {f.code for f in report.errors}


def test_demo_document_passes_all_rules(root_schema: dict, demo_document: dict) -> None:
    report = report_for(demo_document, root_schema)
    assert report.passed, [f.to_dict() for f in report.errors]


def test_report_contract_shape(root_schema: dict, demo_document: dict) -> None:
    payload = report_for(demo_document, root_schema).to_dict()
    assert payload["status"] == "pass"
    assert payload["scope"] == "document"
    assert set(payload) == {"status", "scope", "course_id", "checked_at", "counts", "findings", "skipped_rules"}
    assert set(payload["counts"]) == {"errors", "warnings", "skipped_rules"}


def test_missing_required_section_fails(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    del doc["careers"]
    report = report_for(doc, root_schema)
    assert not report.passed
    assert "required" in codes(report)


def test_blank_string_fails(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["skills"][0]["description"] = "      "
    report = report_for(doc, root_schema)
    assert "blank_string" in codes(report)


def test_placeholder_text_fails(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["recruiters"][0]["description"] = "TODO: fill in a description for this organisation later on."
    report = report_for(doc, root_schema)
    assert "placeholder_text" in codes(report)


def test_soft_placeholder_is_warning_only(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["colleges"]["ranking_source"] = "Demo composite ranking"
    report = report_for(doc, root_schema)
    assert report.passed
    assert "possible_placeholder_text" in {f.code for f in report.warnings}


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d["quick_facts"]["typical_duration"].update({"min_years": 4, "max_years": 3}), "duration_inverted"),
        (lambda d: d["quick_facts"]["indicative_annual_fees"].update({"min": 900000, "max": 20000}), "fee_range_inverted"),
        (lambda d: d["quick_facts"]["indicative_annual_fees"].update({"max": 9_000_000}), "fee_out_of_range"),
        (lambda d: d["snapshot"]["salary"].update({"typical_annual": 90000}), "salary_not_ordered"),
        (lambda d: d["snapshot"]["salary"].update({"higher_annual": 90_000_000}), "salary_out_of_range"),
        (lambda d: d["snapshot"]["salary"].update({"marker_percent": 95}), "salary_marker_mismatch"),
        (lambda d: d["eligibility"]["admission_timeline"][2].update({"step": 5}), "timeline_steps_not_sequential"),
        (lambda d: d["curriculum"]["years"][1].update({"year": 3}), "curriculum_years_not_sequential"),
        (lambda d: d["colleges"]["items"][0].update({"rank": 4}), "college_ranks_not_sequential"),
        (lambda d: d["comparison"][0].update({"course_name": "BA Sociology"}), "comparison_anchor_mismatch"),
        (lambda d: d.update({"course_name": "BSc Chemistry"}), "overview_heading_missing_course"),
    ],
)
def test_cross_field_rules_reject_bad_documents(
    root_schema: dict, demo_document: dict, mutate, expected: str
) -> None:
    doc = copy.deepcopy(demo_document)
    mutate(doc)
    assert expected in codes(report_for(doc, root_schema))


def _year(number: int) -> dict:
    return {
        "year": number,
        "label": f"Year {number}",
        "subjects": [
            {"name": f"Subject {number}{i}", "description": "A distinct subject description for this year."}
            for i in range(4)
        ],
    }


@pytest.mark.parametrize(
    ("min_years", "max_years", "year_count", "should_pass"),
    [
        (3, 4, 4, True),
        (3, 4, 3, False),
        (3, 4, 5, False),
        (4, 4, 4, True),
        (4, 4, 3, False),
        (5, 5, 5, True),
        (5, 5, 4, False),
        (3, 3, 3, True),
        (3, 3, 4, False),
        (5.5, 5.5, 5, True),
    ],
)
def test_curriculum_length_must_match_stated_duration(
    root_schema: dict, demo_document: dict, min_years: int, max_years: int, year_count: int, should_pass: bool
) -> None:
    doc = copy.deepcopy(demo_document)
    doc["quick_facts"]["typical_duration"] = {"min_years": min_years, "max_years": max_years}
    doc["curriculum"]["years"] = [_year(n) for n in range(1, year_count + 1)]
    report = report_for(doc, root_schema)
    assert ("curriculum_length_mismatch" not in codes(report)) is should_pass


def test_four_year_curriculum_is_structurally_valid(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["quick_facts"]["typical_duration"] = {"min_years": 4, "max_years": 4}
    doc["curriculum"]["years"] = [_year(n) for n in range(1, 5)]
    assert report_for(doc, root_schema).passed


def test_a_three_to_four_year_course_must_show_the_fourth_year(
    root_schema: dict, demo_document: dict
) -> None:
    doc = copy.deepcopy(demo_document)
    doc["quick_facts"]["typical_duration"] = {"min_years": 3, "max_years": 4}
    doc["curriculum"]["years"] = [_year(n) for n in range(1, 4)]
    findings = [
        f for f in report_for(doc, root_schema).errors if f.code == "curriculum_length_mismatch"
    ]
    assert findings
    assert "must show all 4" in findings[0].message


def test_six_year_curriculum_exceeds_the_schema(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["quick_facts"]["typical_duration"] = {"min_years": 6, "max_years": 6}
    doc["curriculum"]["years"] = [_year(n) for n in range(1, 7)]
    assert "maxItems" in codes(report_for(doc, root_schema))


def test_variable_fee_row_may_carry_a_typical_range(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["fees"]["rows"][3].update({"min": 1000, "max": 5000})
    assert report_for(doc, root_schema).passed


def test_variable_fee_row_may_omit_the_range_entirely(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["fees"]["rows"][3].update({"min": None, "max": None})
    assert report_for(doc, root_schema).passed


def test_variable_fee_row_rejects_half_a_range(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["fees"]["rows"][3].update({"min": 1000, "max": None})
    assert "variable_fee_half_range" in codes(report_for(doc, root_schema))


def test_non_variable_fee_row_must_have_range(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["fees"]["rows"][0].update({"min": None, "max": None})
    assert "fee_range_missing" in codes(report_for(doc, root_schema))


def test_colleges_must_include_both_institution_types(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    for item in doc["colleges"]["items"]:
        item["institution_type"] = "private"
    assert "college_type_missing" in codes(report_for(doc, root_schema))


def test_duplicate_college_rejected(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["colleges"]["items"][1]["name"] = doc["colleges"]["items"][0]["name"]
    assert "duplicate_college" in codes(report_for(doc, root_schema))


def test_duplicate_subject_rejected(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["curriculum"]["years"][2]["subjects"][0]["name"] = "Cognitive Psychology"
    assert "duplicate_subject" in codes(report_for(doc, root_schema))


def test_career_route_mix_is_a_warning_not_a_failure(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    for career in doc["careers"]:
        career["route_badge"] = "Possible after bachelor's"
    report = report_for(doc, root_schema)
    assert report.passed, "an all-direct-entry course is normal for vocational subjects"
    assert "careers_no_advanced_route" in {f.code for f in report.warnings}

    doc = copy.deepcopy(demo_document)
    for career in doc["careers"]:
        career["route_badge"] = "Postgraduate route"
    report = report_for(doc, root_schema)
    assert report.passed
    assert "careers_no_direct_entry" in {f.code for f in report.warnings}


def test_off_domain_source_rejected(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["verification"]["sources"][0]["url"] = "https://random-blog.example.org/psychology"
    assert "source_off_domain" in codes(report_for(doc, root_schema))


def test_subdomain_of_allowed_domain_accepted(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["verification"]["sources"][0]["url"] = "https://info.ugc.gov.in/curriculum"
    assert report_for(doc, root_schema).passed


def test_grounding_unverified_warning_when_no_domains(root_schema: dict, demo_document: dict) -> None:
    report = report_for(demo_document, root_schema, CTX_NO_DOMAINS)
    assert report.passed
    assert "grounding_unverified" in {f.code for f in report.warnings}


def test_overview_length_out_of_band(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["overview"]["paragraphs"] = [("word " * 40).strip() + "."] * 3
    assert "overview_length" in codes(report_for(doc, root_schema))


def test_rules_skip_cleanly_on_partial_documents(root_schema: dict, demo_document: dict) -> None:
    partial = {"careers": demo_document["careers"], "recruiters": demo_document["recruiters"]}
    report = validate_document(partial, {"type": "object"}, CTX, scope="chunk:outcomes")
    assert report.passed
    assert "comparison_anchor" in report.skipped_rules
    assert "college_ranking" in report.skipped_rules


def test_zero_minimum_fee_row_is_not_a_free_pass(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["fees"]["rows"][0].update({"min": 0, "max": 500000, "institution_type": None})
    report = report_for(doc, root_schema)
    assert "fee_spread_too_wide" in codes(report)
    assert "unbounded" in next(f.message for f in report.errors if f.code == "fee_spread_too_wide")


def test_zero_minimum_quick_fee_is_not_a_free_pass(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["quick_facts"]["indicative_annual_fees"] = {"min": 0, "max": 500000}
    assert "quick_fee_spread_too_wide" in codes(report_for(doc, root_schema))


def test_free_course_with_a_tight_ceiling_still_passes(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["fees"]["rows"][0].update({"min": 0, "max": 0, "institution_type": "government"})
    doc["fees"]["rows"].append(
        {
            "category": "Tuition (private)",
            "institution_type": "private",
            "min": 150000,
            "max": 400000,
            "is_variable": False,
            "frequency": "Per year",
            "parent_check": "Compare included facilities and hostel charges",
        }
    )
    assert report_for(doc, root_schema).passed


def test_segmented_zero_minimum_row_is_exempt(root_schema: dict, demo_document: dict) -> None:
    doc = copy.deepcopy(demo_document)
    doc["fees"]["rows"][0].update({"min": 0, "max": 60000, "institution_type": "government"})
    doc["fees"]["rows"].append(
        {
            "category": "Tuition (private)",
            "institution_type": "private",
            "min": 150000,
            "max": 400000,
            "is_variable": False,
            "frequency": "Per year",
            "parent_check": "Compare included facilities",
        }
    )
    assert "fee_spread_too_wide" not in codes(report_for(doc, root_schema))


def test_government_total_programme_row_is_not_compared_to_the_market_annual_max(
    root_schema: dict, demo_document: dict
) -> None:
    doc = copy.deepcopy(demo_document)
    doc["quick_facts"]["indicative_annual_fees"] = {"min": 20000, "max": 1000000}
    doc["fees"]["rows"][3] = {
        "category": "Total programme, government",
        "institution_type": "government",
        "min": 5356,
        "max": 17300,
        "is_variable": False,
        "frequency": "Total programme",
        "parent_check": "Confirm the full multi-year cost with the college",
    }
    assert "total_below_annual" not in codes(report_for(doc, root_schema))
