from src.courses.taxonomy import load_taxonomy


def test_cross_listed_rows_merge_into_750_courses():
    courses = load_taxonomy()
    assert len(courses) == 750


def _course_named(courses, name: str):
    return next(c for c in courses if c.standard_course_name == name)


def test_comma_separated_cells_split_into_individual_aliases():
    course = _course_named(load_taxonomy(), "Physical & Occupational Therapy")
    assert course.aliases == [
        "B.P.T.",
        "B.Sc. Physiotherapy",
        "B.O.T.",
        "B.Sc. Occupational Therapy",
    ]


def test_commas_inside_a_bulleted_alias_are_not_split():
    course = _course_named(load_taxonomy(), "Allopathic Medicine & Surgery (Core)")
    assert "MBBS (Bachelor of Medicine, Bachelor of Surgery)" in course.aliases


def test_cross_listed_courses_keep_both_field_associations():
    courses = load_taxonomy()
    multi_field = {c.standard_course_name.lower() for c in courses if len(c.fields) > 1}
    assert multi_field == {
        "interior design",
        "engineering physics",
        "digital humanities",
        "physical education (teaching track)",
    }


def test_every_course_has_at_least_one_alias():
    without = [c.standard_course_name for c in load_taxonomy() if not c.aliases]
    assert without == []


def test_course_ids_are_unique():
    courses = load_taxonomy()
    assert len({c.course_id for c in courses}) == len(courses)


def test_total_alias_count_is_stable():
    assert sum(len(c.aliases) for c in load_taxonomy()) == 4291
