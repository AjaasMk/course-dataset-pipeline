from pathlib import Path

from src.retrieve.orchestrator import load_config

PILOT_COURSES_PATH = Path("config/pilot_courses.yaml")


def test_pilot_courses_has_fifty_entries():
    pilot = load_config(path=PILOT_COURSES_PATH)
    assert len(pilot["courses"]) == 50


def test_pilot_courses_stratified_by_category():
    pilot = load_config(path=PILOT_COURSES_PATH)
    counts = {}
    for course in pilot["courses"]:
        counts[course["category"]] = counts.get(course["category"], 0) + 1

    assert counts == {
        "engineering": 20,
        "medicine": 10,
        "commerce_management": 5,
        "law": 5,
        "animation_design": 5,
        "media_mass_comm": 5,
    }


