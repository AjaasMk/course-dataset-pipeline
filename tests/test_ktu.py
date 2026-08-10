import pytest

from src.retrieve.ktu import KTUSyllabus, branch_index, scheme_matches


def _syllabus(branch, path="data/raw/KTU/x.pdf"):
    return KTUSyllabus(
        branch_name=branch,
        scheme_name="B.Tech Full Time 2024 Scheme",
        programme="B.Tech",
        academic_year="2024 - 2025",
        filename="x.pdf",
        local_path=path,
    )


@pytest.mark.parametrize(
    "name",
    [
        "B.Tech Full Time 2024 Scheme",
        "B. Tech Working Professional 2024 scheme",
    ],
)
def test_both_real_2024_schemes_match_the_year(name):
    # KTU runs two distinct 2024 schemes -- Full Time and Working Professional.
    # The year alone does not identify one, so the caller must disambiguate;
    # matching only one of them here would silently drop a real scheme.
    assert scheme_matches(name, "2024")


@pytest.mark.parametrize(
    "name",
    ["B.TECH FULL TIME 2015", "B.Tech Full Time 2019 Scheme", "B.Tech Part Time 2020 Scheme"],
)
def test_other_real_scheme_years_do_not_match_2024(name):
    assert not scheme_matches(name, "2024")


def test_branch_index_maps_branch_name_to_its_syllabus_path():
    # Same shape every other adapter's build_index() returns, so course-to-branch
    # matching reuses the shared scorer and per-source threshold.
    index = branch_index(
        [
            _syllabus("COMPUTER SCIENCE AND ENGINEERING", "data/raw/KTU/cse.pdf"),
            _syllabus("ARTIFICIAL INTELLIGENCE AND DATA SCIENCE", "data/raw/KTU/aids.pdf"),
        ]
    )

    assert index["COMPUTER SCIENCE AND ENGINEERING"] == "data/raw/KTU/cse.pdf"
    assert index["ARTIFICIAL INTELLIGENCE AND DATA SCIENCE"] == "data/raw/KTU/aids.pdf"


def test_a_branch_whose_download_failed_is_left_out_of_the_index():
    # harvest_syllabi() records nothing for a branch whose download did not
    # complete. An index entry pointing at no file would resolve an intent to a
    # document that cannot be read.
    index = branch_index([_syllabus("CIVIL ENGINEERING", ""), _syllabus("CSE", "data/raw/KTU/c.pdf")])

    assert "CIVIL ENGINEERING" not in index
    assert index["CSE"] == "data/raw/KTU/c.pdf"


def test_two_branches_sharing_a_name_keep_the_last_harvested_path():
    # KTU lists near-duplicate branch labels across programme types. The index
    # is a plain name->path map like every other adapter's, so a later entry
    # wins; this documents that rather than leaving it to chance.
    index = branch_index([_syllabus("CSE", "a.pdf"), _syllabus("CSE", "b.pdf")])

    assert index["CSE"] == "b.pdf"
