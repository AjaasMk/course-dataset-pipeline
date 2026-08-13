"""Project our fact records into the client's course-schema.json shape.

Their schema is a VIEW model -- sections, panels, cards, items, shaped for
rendering. Ours is a FACT model -- flat records keyed by F-number, each field
carrying the quotation that backs it. Only one field name is common to both,
and that is correct rather than a defect: they describe different things.

Collapsing ours into theirs would lose the citation trail, because their schema
holds provenance once at page level (course.source) and nowhere per field. So
the facts stay as they are and this projects them, emitting their exact paths.
Anything with no evidence emits null or an empty list rather than a plausible
value, which their own validation rules then flag -- deliberately, since a page
that validates by inventing content is worse than one that fails honestly.
"""

from typing import Any, Optional

# their path -> where the value comes from on our side. Written out rather than
# inferred, because the mapping is a client agreement: a wrong guess here ships
# a wrong page, and a reader needs to see the correspondence to check it.
FIELD_MAP = {
    "metadata.title": ("Course Identity", "standard_course_name"),
    "metadata.description": ("Course Overview", "hero_summary"),
    "hero.title": ("Course Identity", "standard_course_name"),
    "hero.summary": ("Course Overview", "hero_summary"),
    "quickGrid.duration": ("Duration & Mode", "minimum_duration"),
    "quickGrid.entry": ("Eligibility", "minimum_qualification"),
    "quickGrid.streams": ("Eligibility", "accepted_streams"),
    "quickGrid.learning": ("Curriculum", "learning_activities"),
    "quickGrid.fees": ("Fees", "tuition_fee"),
    "quickGrid.career": ("Career Mapping", "typical_entry_role"),
}

# Fields their page renders that nothing on our side can supply. Named here so
# the gap is a documented decision rather than a silent null.
UNMAPPABLE = {
    "hero.fitPanel.score": "per-student fit score, computed against an "
                           "assessment this pipeline does not hold",
    "sections.colleges.cards[].logo": "institution logos are not collected",
    "sections.recruiters.cards[].logo": "recruiter logos are not collected",
}

QUICK_CARDS = [
    ("clock", "Typical duration", "quickGrid.duration"),
    ("graduation", "Entry level", "quickGrid.entry"),
    ("books", "Suitable streams", "quickGrid.streams"),
    ("flask", "Learning style", "quickGrid.learning"),
    ("money", "Indicative fees", "quickGrid.fees"),
    ("compass", "Career direction", "quickGrid.career"),
]

SECTION_TITLES = {
    "snapshot": ("Course snapshot", "Salary outlook and specialisation pathways", "Decision snapshot"),
    "overview": ("What is this course?", "A simple explanation for students and parents", "Overview"),
    "fit": ("Is this course suitable for you?", "Interest, learning preference and reality check", "Student decision support"),
    "eligibility": ("Eligibility and admission", "Requirements vary by university", "Verify institution rules"),
    "subjects": ("What will you study?", "Subjects established from official curricula", "Year-wise tabs"),
    "skills": ("Skills you can develop", "Subject knowledge and transferable skills", "Skill areas"),
    "careers": ("Career opportunities", "Direct-entry roles separated from regulated roles", "Career-route clarity"),
    "recruiters": ("Top recruiters and employment sectors", "Organisations with the roles they recruit for", "Directory"),
    "pathway": ("Further-study pathway", "One route toward a specialised career", ""),
    "fees": ("Fees and total study cost", "Official fee schedules", "Parent priority"),
    "colleges": ("Top colleges and universities", "Ranked directory", "Ranking"),
    "compare": ("Compare similar courses", "Meaningful differences between alternatives", "Decision table"),
    "nextSteps": ("What should you do now?", "Guidance by school stage", ""),
    "parentCorner": ("Parent corner", "Questions that support family discussion", "Parent guide"),
    "faq": ("Frequently asked questions", "Short, expandable answers", "FAQs"),
}


def _value(facts: dict, segment: str, field: str) -> Any:
    return (facts.get(segment) or {}).get(field)


def _as_text(value: Any) -> Optional[str]:
    if value in (None, "", [], {}):
        return None
    return ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)


def _section(section_id: str, **extra) -> dict:
    title, subtitle, tag = SECTION_TITLES[section_id]
    return {"id": section_id, "title": title, "subtitle": subtitle, "tag": tag, **extra}


def _untagged(section_id: str, **extra) -> dict:
    """nextSteps and pathway carry no `tag` key in their schema."""
    title, subtitle, _ = SECTION_TITLES[section_id]
    return {"id": section_id, "title": title, "subtitle": subtitle, **extra}


def _join_paragraphs(paragraphs):
    """overview.content is one string in their schema, not a paragraph list."""
    if not paragraphs:
        return None
    if isinstance(paragraphs, str):
        return paragraphs
    return "\n\n".join(str(p) for p in paragraphs)


def _subject_tabs(subjects: list) -> list[dict]:
    """Their subjects section is year-tabbed; ours may not know the year.

    Subjects with no year land in a single tab rather than being spread across
    three on a guess -- a subject shown under the wrong year is a factual error,
    an unassigned one is only a presentational compromise.
    """
    by_year: dict[Any, list] = {}
    for subject in subjects:
        if isinstance(subject, dict):
            by_year.setdefault(subject.get("year"), []).append(subject)
        else:
            by_year.setdefault(None, []).append({"name": subject})

    tabs = []
    for year in sorted(by_year, key=lambda y: (y is None, y or 0)):
        label = f"Year {year}" if year else "Subjects"
        tabs.append({
            "id": f"year{year}" if year else "subjects",
            "label": label,
            "content": {"type": "grid", "items": [
                {"title": s.get("name"), "description": s.get("description")}
                for s in by_year[year]
            ]},
        })
    return tabs


def project(course_id: str, course_name: str, facts: dict, generated: dict,
            field_of_study: str = "", level: str = "Undergraduate") -> dict:
    """Build the client's course object from our facts plus generated blocks.

    `facts` is {segment: {field: value}}; `generated` is {block: {field: value}}
    for the advisory sections no source publishes.
    """
    def fact(path: str) -> Any:
        segment, field = FIELD_MAP[path]
        return _value(facts, segment, field)

    def block(name: str, field: str) -> Any:
        return (generated.get(name) or {}).get(field)

    subjects = _value(facts, "Curriculum", "subjects") or \
        _value(facts, "Curriculum", "core_subjects") or []

    return {"course": {
        "metadata": {
            "id": course_id,
            "title": _as_text(fact("metadata.title")) or course_name,
            "description": _as_text(fact("metadata.description")),
            "lastUpdated": None,
            "status": "Draft",
        },
        "breadcrumb": {"items": [
            {"label": "Home", "path": "/"},
            {"label": "Courses", "path": "/courses"},
            {"label": field_of_study, "path": f"/courses/{field_of_study}"},
            {"label": course_name, "path": f"/courses/{course_id}"},
        ]},
        "hero": {
            "title": _as_text(fact("hero.title")) or course_name,
            "summary": _as_text(fact("hero.summary")),
            "labels": [{"type": "level", "text": level},
                       {"type": "field", "text": field_of_study}],
            "fitPanel": {
                "title": "Your possible fit",
                "subtitle": "Illustrative score based on interests and learning preferences.",
                # Named in UNMAPPABLE: no source, and inventing a score for a
                # student we know nothing about would be the worst kind of guess.
                "score": None,
                "highlights": block("hero.fit_panel", "fit_statements") or [],
            },
        },
        "quickGrid": {"cards": [
            {"icon": icon, "label": label, "value": _as_text(fact(path)), "note": None}
            for icon, label, path in QUICK_CARDS
        ]},
        "sections": {
            "snapshot": _section("snapshot", panels=[
                {"type": "salary", "title": "Indicative salary range",
                 "subtitle": "Published salary evidence for this course.",
                 "salaryValues": [
                     {"label": "Lower range", "amount": _value(facts, "Salary", "salary_min"), "featured": False},
                     {"label": "Typical average", "amount": _value(facts, "Salary", "salary_average"), "featured": True},
                     {"label": "Higher range", "amount": _value(facts, "Salary", "salary_max"), "featured": False},
                 ],
                 "salaryScale": {"min": _value(facts, "Salary", "salary_min"),
                                 "max": _value(facts, "Salary", "salary_max"),
                                 "marker": _value(facts, "Salary", "salary_average")},
                 "note": None},
                {"type": "specialisation", "title": "Popular specialisations",
                 "subtitle": "Specialisations named in official course documents.",
                 "items": _value(facts, "Specialisation", "specialisation_name") or [],
                 "note": None},
            ]),
            "overview": _section("overview", content=_join_paragraphs(
                block("Course Overview", "overview_paragraphs"))),
            "fit": _section("fit", boxes=[
                {"type": "positive", "title": "You may enjoy this course if you…",
                 "items": block("fit", "enjoy_if") or []},
                {"type": "caution", "title": "Think carefully if you…",
                 "items": block("fit", "think_carefully_if") or []},
            ], tags=block("fit", "tags") or []),
            "eligibility": _section("eligibility", infoBoxes=[
                {"title": "Typical eligibility",
                 "items": _value(facts, "Eligibility", "accepted_streams") or []},
                {"title": "Possible admission methods",
                 "items": _value(facts, "Entrance & Admission", "applicable_courses") or []},
            ], timeline={"steps": [
                {"number": i, "title": step, "description": None}
                for i, step in enumerate(
                    _value(facts, "Entrance & Admission", "admission_steps") or [], 1)
            ]}),
            "subjects": _section("subjects", tabs=_subject_tabs(subjects)),
            "skills": _section("skills", cards=block("Skills Developed", "skills") or []),
            "careers": _section("careers", cards=[
                {"title": _value(facts, "Career Mapping", "typical_entry_role"),
                 "description": _value(facts, "Career Mapping", "career_note"),
                 "badge": _value(facts, "Career Mapping", "relationship_strength"),
                 "route": _value(facts, "Career Mapping", "career_progression")}
            ] if _value(facts, "Career Mapping", "typical_entry_role") else []),
            "recruiters": _section("recruiters", cards=[
                {"logo": None,
                 "name": _value(facts, "Recruiters & Placement", "recruiter_name"),
                 "sector": _value(facts, "Recruiters & Placement", "recruiter_sector"),
                 "description": _value(facts, "Recruiters & Placement", "recruiter_note"),
                 "roles": _value(facts, "Recruiters & Placement", "role_recruited_for") or []}
            ] if _value(facts, "Recruiters & Placement", "recruiter_name") else []),
            "pathway": _untagged("pathway",
                                 items=block("Further-Study Pathways", "pathway") or []),
            "fees": _section("fees", table={
                "headers": ["Cost category", "Indicative range", "Frequency",
                            "What parents should check"],
                "rows": _fee_rows(facts),
            }),
            "colleges": _section("colleges",
                                 filters=[{"id": "all", "label": "All institutions"},
                                          {"id": "government", "label": "Government"},
                                          {"id": "private", "label": "Private"}],
                                 source=_value(facts, "Ranking & Accreditation", "ranking_body"),
                                 cards=_college_cards(facts)),
            "compare": _section("compare", table={
                "headers": ["Feature", course_name] + (block("compare", "comparison_courses") or []),
                "rows": [{"feature": r.get("feature"),
                          "values": [r.get("this_course"), r.get("alternative_1"),
                                     r.get("alternative_2")]}
                         for r in (block("compare", "rows") or [])],
            }),
            "nextSteps": _untagged("nextSteps", cards=[
                {"title": stage, "grade": grade, "description": block("what_now", key)}
                for stage, grade, key in (
                    ("Grades 8-10: Explore", "8-10", "grades_8_10"),
                    ("Grade 11: Prepare", "11", "grade_11"),
                    ("Grade 12: Apply", "12", "grade_12"))
                if block("what_now", key)
            ]),
            "parentCorner": _section("parentCorner",
                                     intro=block("parent_corner", "intro"),
                                     questions=block("parent_corner", "questions") or []),
            # Their faq items carry an  flag controlling which accordion
            # entry starts expanded; the first one, as in their own example.
            "faq": _section("faq", items=[
                {"question": item.get("question"), "answer": item.get("answer"),
                 "open": index == 0}
                for index, item in enumerate(block("faq", "faqs") or [])
            ]),
        },
        "sidebar": {"cards": [
            {"type": "action", "title": "Plan your next step",
             "subtitle": "Save your progress and return to this course from your dashboard.",
             "progress": None,
             "buttons": [{"text": "Save this course", "action": "save"},
                         {"text": "Compare courses", "action": "compare"},
                         {"text": "Share with parent", "action": "share"}]},
            {"type": "checklist", "title": "Course checklist", "items": []},
            {"type": "cta", "title": "Need personal guidance?",
             "subtitle": "Discuss course fit, subject selection and pathways with a career counsellor.",
             "button": None},
        ]},
        "source": {
            "verified": "sourced where cited",
            "lastReviewed": None,
            "status": "Draft",
            "reviewer": None,
        },
    }}


def _fee_rows(facts: dict) -> list[dict]:
    """Their fee table is long-format; ours is one column per fee type."""
    fees = facts.get("Fees") or {}
    labels = [("tuition_fee", "Tuition"), ("admission_fee", "Admission"),
              ("examination_fee", "Examination"), ("hostel_fee", "Hostel and living"),
              ("mess_fee", "Mess"), ("transport_fee", "Transport")]
    return [
        {"category": label, "range": fees[key],
         "frequency": fees.get("fee_frequency"),
         "note": fees.get("parent_check_note")}
        for key, label in labels if fees.get(key)
    ]


def _college_cards(facts: dict) -> list[dict]:
    offering = facts.get("Institution & Offering") or {}
    ranking = facts.get("Ranking & Accreditation") or {}
    if not offering.get("official_institution_name"):
        return []
    score = ranking.get("ranking_score")
    meta = [v for v in (offering.get("ownership_type"),
                        f"Score: {score}" if score else None,
                        offering.get("admission_route"),
                        offering.get("offering_highlight")) if v]
    return [{
        "rank": ranking.get("rank"),
        "type": offering.get("ownership_type"),
        "name": offering.get("official_institution_name"),
        "location": offering.get("city_or_region"),
        "program": offering.get("course_variant"),
        "duration": None,
        "score": score,
        "meta": meta,
        "fees": offering.get("annual_fee"),
    }]
