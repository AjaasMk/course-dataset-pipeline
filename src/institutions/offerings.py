from pathlib import Path
from typing import Optional

from src.institutions import store
from src.institutions.models import InstitutionCourseOffering

SOURCE_ID = "NIRF"

# A NIRF ranking says the institution works in a discipline. It does not say the
# institution runs a particular course, so an offering derived from it carries
# discipline-level confidence only -- deliberately below the acceptance
# threshold. Confirming a real offering needs the institution's own course page.
CATEGORY_LEVEL_CONFIDENCE = 0.5

_GENERAL_CATEGORIES = ["University", "College"]

# Taxonomy sheet -> NIRF discipline tables. NIRF ranks 13 disciplines against the
# taxonomy's 30 fields, so most fields have no discipline table of their own and
# fall back to the general rankings.
_FIELD_TO_CATEGORIES = {
    "Engineering & Applied Technolog": ["Engineering"],
    "Computing, AI & Information Sys": ["Engineering"],
    "Mathematics, Statistics & Analy": ["University", "College"],
    "Architecture, Planning & Built": ["Architecture"],
    "Medicine, Dentistry & Clinical ": ["Medical", "Dental"],
    "Nursing, Pharmacy & Allied Heal": ["Pharmacy", "Medical"],
    "Public Health & Healthcare Mana": ["Medical", "Management"],
    "Rehabilitation, Disability & Sp": ["Medical"],
    "Law, Governance & Public Policy": ["Law"],
    "Business, Management & Entrepre": ["Management"],
    "Accounting, Finance, Economics ": ["Management"],
    "Agriculture, Food & Natural Res": ["Agriculture"],
    "Veterinary & Animal Sciences": ["Agriculture"],
}


def nirf_categories_for_field(field: str) -> list[str]:
    return _FIELD_TO_CATEGORIES.get(field, list(_GENERAL_CATEGORIES))


def candidate_offerings(
    course_id: str,
    fields: list[str],
    year: str,
    limit: int,
    db_path: Optional[Path] = None,
) -> list[InstitutionCourseOffering]:
    categories: list[str] = []
    for field in fields:
        for category in nirf_categories_for_field(field):
            if category not in categories:
                categories.append(category)

    offerings: list[InstitutionCourseOffering] = []
    seen: set[str] = set()
    for category in categories:
        for institution in store.top_ranked(category, year, limit, db_path=db_path):
            if institution.institution_id in seen:
                continue
            seen.add(institution.institution_id)
            offerings.append(
                InstitutionCourseOffering(
                    institution_id=institution.institution_id,
                    course_id=course_id,
                    discovered_from_source_id=SOURCE_ID,
                    confidence=CATEGORY_LEVEL_CONFIDENCE,
                )
            )
    return offerings
