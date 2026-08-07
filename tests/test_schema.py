from src.schema import (
    CollegesAvailable,
    CourseDetail,
    Eligibility,
    EntranceExams,
    FAQ,
    Fees,
    FeeRange,
    JobProfile,
    ManifestEntry,
    Syllabus,
    SyllabusSemester,
    SourceType,
    TopCollege,
)


def test_manifest_entry_defaults_new_fields_to_none():
    entry = ManifestEntry(
        course_name="Mechanical Engineering",
        tier="engineering",
        source_type=SourceType.REGULATOR_PDF,
        match_confidence=0.92,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )
    assert entry.content_type is None
    assert entry.content_length is None
    assert entry.http_status is None


def test_source_type_has_aggregator_webpage_value():
    assert SourceType.AGGREGATOR_WEBPAGE.value == "aggregator_webpage"


def test_source_type_has_no_general_background_value():
    assert not hasattr(SourceType, "GENERAL_BACKGROUND_WEBPAGE")


def test_manifest_entry_accepts_source_type_enum():
    entry = ManifestEntry(
        course_name="Some Course",
        tier="engineering",
        source_type=SourceType.AGGREGATOR_WEBPAGE,
        match_confidence=0.5,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )
    assert entry.source_type == SourceType.AGGREGATOR_WEBPAGE


def test_course_detail_defaults_optional_fields_to_none():
    course = CourseDetail(course_name="Chemical Engineering", category="engineering")
    assert course.duration is None
    assert course.description is None
    assert course.eligibility is None
    assert course.fees is None
    assert course.colleges_available is None
    assert course.syllabus is None
    assert course.average_salary_lpa is None
    assert course.degrees_offered == []
    assert course.job_profiles == []
    assert course.top_colleges == []
    assert course.related_courses == []
    assert course.faqs == []


def test_course_detail_has_no_source_refs_field():
    assert "source_refs" not in CourseDetail.model_fields


def test_course_detail_accepts_nested_fields():
    course = CourseDetail(
        course_name="Chemical Engineering",
        category="engineering",
        degrees_offered=["BE", "B.Tech", "MTech", "PhD"],
        duration="B.Tech/BE: 4 years, M.Tech/ME: 2 years",
        eligibility=Eligibility(ug="Class 12 with PCM", pg="Bachelor's in a related field"),
        entrance_exams=EntranceExams(ug=["JEE Main"], pg=["GATE"]),
        fees=Fees(ug=FeeRange(max_private=2526000, max_government=1316000)),
        colleges_available=CollegesAvailable(private_count=280, government_count=208),
        job_profiles=[JobProfile(title="Chemical Engineer", avg_salary_lpa=5.1)],
        syllabus=Syllabus(
            ug_semesters=[SyllabusSemester(semester=1, subjects=["Mathematics", "Physics"])]
        ),
        average_salary_lpa=5.1,
        top_colleges=[TopCollege(name="IIT Bombay", type="government", nirf_rank=3, fees=859000)],
        related_courses=["Petrochemical Engineering", "Materials Engineering"],
        faqs=[FAQ(question="Can I do a diploma?", answer="Yes, after Class 10.")],
    )
    assert course.eligibility.ug == "Class 12 with PCM"
    assert course.entrance_exams.pg == ["GATE"]
    assert course.fees.ug.max_private == 2526000
    assert course.colleges_available.private_count == 280
    assert course.job_profiles[0].avg_salary_lpa == 5.1
    assert course.syllabus.ug_semesters[0].subjects == ["Mathematics", "Physics"]
    assert course.average_salary_lpa == 5.1
    assert course.top_colleges[0].nirf_rank == 3
    assert course.related_courses == ["Petrochemical Engineering", "Materials Engineering"]
    assert course.faqs[0].question == "Can I do a diploma?"
