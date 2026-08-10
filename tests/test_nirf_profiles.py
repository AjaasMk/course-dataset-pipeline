import pytest

from src.institutions.models import RankedProfile
from src.institutions.nirf_profiles import (
    parse_intake,
    parse_placements,
    profile_targets,
    profile_url,
)

# Every fixture below is real text extracted from the live NIRF profile PDF for
# IR-G-U-0101 (Indian Agricultural Research Institute), not invented. The two
# placement tables genuinely differ in column count -- UG carries an extra
# academic-year and lateral-entry pair that PG does not -- which is why the
# parser anchors on the salary pattern rather than counting columns.
_UG_PLACEMENT_BLOCK = """Placement & Higher Studies
UG [4 Years Program(s)]: Placement & higher studies for previous 3 years
Academic Year No. of first year
students intake in the
year
No. of first year
students admitted in
the year
Academic Year No. of students
admitted through
Lateral entry
Academic Year No. of students
graduating in
minimum stipulated
time
No. of students
placed
Median salary of
placed graduates per
annum(Amount in
Rs.)
No. of students
selected for Higher
Studies
2018-19 0 0 2019-20 0 2021-22 0 0 0(Zero) 0
2019-20 0 0 2020-21 0 2022-23 0 0 0(Zero) 0
2020-21 220 218 2021-22 4 2023-24 210 55 850000(Eight Lakh Fifty Thousand) 96
"""

# Verbatim from the real PDF, wrapping included. A PG row does NOT stay on one
# line: the spelled-out salary runs over several lines and the trailing
# higher-studies count lands on its own. An earlier version of this parser
# matched only single-line rows and silently found nothing here -- it reported
# three all-zero UG rows and dropped every real salary in the document.
_PG_PLACEMENT_BLOCK = """PG [2 Years Program(s)]: Placement & higher studies for previous 3 years
Academic Year No. of first year
students intake in the
year
No. of first year
students admitted in
the year
Academic Year No. of students graduating in minimum
stipulated time
No. of students
placed
Median salary of
placed graduates per
annum(Amount in
Rs.)
No. of students
selected for Higher
Studies
2020-21 238 235 2021-22 222 70 996336(Nine Lakh
Ninety Six Thousand
Three Hundred and
Thirty Six)
136
2021-22 257 257 2022-23 239 26 628680(Six Lakh
Twenty Eight
Thousand Six Hundred
and Eighty)
171
2022-23 280 280 2023-24 236 27 696000(Six Lakh
Ninety Six Thousand)
170
Ph.D Student Details
Ph.D (Student pursuing doctoral program till 2023-24)
Total Students
Full Time 1354
"""

_INTAKE_BLOCK = """Sanctioned (Approved) Intake
Academic Year 2023-24 2022-23 2021-22 2020-21 2019-20 2018-19
UG [4 Years Program(s)] 463 330 0 0 - -
PG [2 Year Program(s)] 323 280 - - - -
Total Actual Student Strength (Program(s) Offered by your Institution)
"""


def test_profile_url_uses_the_real_cdn_pattern():
    assert profile_url("IR-G-U-0101", "Agriculture", "2025") == (
        "https://www.nirfindia.org/nirfpdfcdn/2025/pdf/Agriculture/IR-G-U-0101.pdf"
    )


def test_pg_placement_rows_are_parsed_across_their_real_line_wrapping():
    records = parse_placements(_PG_PLACEMENT_BLOCK)

    assert len(records) == 3
    latest = records[-1]
    assert latest.programme_level == "PG"
    assert latest.academic_year == "2023-24"
    assert latest.students_graduating == 236
    assert latest.students_placed == 27
    assert latest.median_salary_rupees == 696000
    assert latest.students_higher_studies == 170


def test_the_final_row_is_read_even_though_a_new_section_follows_it():
    # The last PG row is followed immediately by "Ph.D Student Details" with no
    # blank line. A parser that accumulates continuation lines until the next
    # row-start swallows that heading into the row and loses it -- which is
    # what dropped the real 696000 salary from IR-G-U-0101.
    records = parse_placements(_PG_PLACEMENT_BLOCK)

    last = records[-1]
    assert last.academic_year == "2023-24"
    assert last.median_salary_rupees == 696000
    assert last.students_higher_studies == 170


def test_a_salary_whose_words_wrap_over_four_lines_is_still_read():
    # 996336 spells out to "Nine Lakh Ninety Six Thousand Three Hundred and
    # Thirty Six", which the PDF breaks across four lines before the
    # higher-studies count on a fifth. This is the row that exposed the
    # single-line assumption.
    records = parse_placements(_PG_PLACEMENT_BLOCK)

    first = records[0]
    assert first.academic_year == "2021-22"
    assert first.median_salary_rupees == 996336
    assert first.students_placed == 70
    assert first.students_higher_studies == 136


def test_ug_placement_row_is_parsed_despite_the_extra_lateral_entry_columns():
    records = parse_placements(_UG_PLACEMENT_BLOCK)

    assert [r.programme_level for r in records] == ["UG", "UG", "UG"]
    latest = records[-1]
    assert latest.academic_year == "2023-24"
    assert latest.students_graduating == 210
    assert latest.students_placed == 55
    assert latest.median_salary_rupees == 850000
    assert latest.students_higher_studies == 96


def test_a_zero_salary_row_is_kept_as_zero_not_dropped():
    # "0(Zero)" is a real, meaningful value -- the institution reported no
    # placements that year. That is not missing data and must not become None.
    records = parse_placements(_UG_PLACEMENT_BLOCK)

    first = records[0]
    assert first.academic_year == "2021-22"
    assert first.median_salary_rupees == 0
    assert first.students_placed == 0


def test_intake_is_parsed_per_programme_level_and_year():
    records = parse_intake(_INTAKE_BLOCK)

    by_key = {(r.programme_level, r.academic_year): r.sanctioned_intake for r in records}
    assert by_key[("UG", "2023-24")] == 463
    assert by_key[("UG", "2022-23")] == 330
    assert by_key[("PG", "2023-24")] == 323
    assert by_key[("PG", "2022-23")] == 280


def test_a_dash_intake_cell_is_omitted_rather_than_read_as_zero():
    # The real PDF writes "-" where an institution reported nothing. Reading
    # that as 0 would assert the institution sanctioned zero seats, which is a
    # different and false claim (Hard Constraint 4).
    records = parse_intake(_INTAKE_BLOCK)

    years = {(r.programme_level, r.academic_year) for r in records}
    assert ("UG", "2019-20") not in years
    assert ("PG", "2021-22") not in years
    assert ("UG", "2021-22") in years  # a real 0, kept


@pytest.mark.parametrize("text", ["", "Placement & Higher Studies\nheader only, no rows\n"])
def test_a_block_with_no_data_rows_yields_nothing_rather_than_raising(text):
    assert parse_placements(text) == []


def test_malformed_row_is_skipped_not_guessed():
    # A row that looks like a data row but has no salary anchor cannot be
    # positionally disambiguated between the UG and PG layouts. Skipping it is
    # correct; inventing a column mapping is not.
    broken = "PG [2 Years Program(s)]: Placement & higher studies for previous 3 years\n2022-23 280 280 2023-24 236\n"

    assert parse_placements(broken) == []


def _institution(nirf_id, category, name="X", year="2025"):
    return RankedProfile(
        institution_id=f"INST-{nirf_id}",
        canonical_name=name,
        nirf_id=nirf_id,
        ranking_category=category,
        ranking_year=year,
    )


def test_profile_targets_yields_one_url_per_institution():
    targets = profile_targets(
        [
            _institution("IR-G-U-0101", "Agriculture", "IARI"),
            _institution("IR-M-S-8890", "Management", "IIM Ahmedabad"),
        ]
    )

    assert [t.document_url for t in targets] == [
        "https://www.nirfindia.org/nirfpdfcdn/2025/pdf/Agriculture/IR-G-U-0101.pdf",
        "https://www.nirfindia.org/nirfpdfcdn/2025/pdf/Management/IR-M-S-8890.pdf",
    ]


def test_profile_target_title_identifies_the_institution_and_category():
    only = profile_targets([_institution("IR-G-U-0101", "Agriculture", "IARI")])[0]

    assert "IARI" in only.document_title
    assert "Agriculture" in only.document_title


def test_the_same_institution_ranked_in_two_categories_yields_both_profiles():
    # NIRF ranks one institution in several disciplines and publishes a
    # SEPARATE profile PDF per category, so these are two real documents, not
    # a duplicate to collapse.
    targets = profile_targets(
        [
            _institution("IR-O-U-0377", "Overall", "IISER Mohali"),
            _institution("IR-E-U-0377", "Engineering", "IISER Mohali"),
        ]
    )

    assert len(targets) == 2
    assert {t.document_url for t in targets} == {
        "https://www.nirfindia.org/nirfpdfcdn/2025/pdf/Overall/IR-O-U-0377.pdf",
        "https://www.nirfindia.org/nirfpdfcdn/2025/pdf/Engineering/IR-E-U-0377.pdf",
    }


@pytest.mark.parametrize(
    "nirf_id,category",
    [("", "Agriculture"), ("IR-G-U-0101", "")],
)
def test_a_profile_missing_id_or_category_is_skipped_not_guessed(nirf_id, category):
    # The URL is only constructible from a real nirf_id and category. Guessing
    # either would fetch some other institution's profile and attribute it to
    # this one -- and a wrong category is not harmless: /University/ and
    # /Overall/ for the same id return genuinely different documents.
    profile = _institution(nirf_id, category, "Blank")

    assert profile_targets([profile]) == []
