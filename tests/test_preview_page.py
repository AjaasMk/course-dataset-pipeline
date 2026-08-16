from __future__ import annotations

import collections
import re
from pathlib import Path

import pytest

PREVIEW = Path(__file__).resolve().parents[1] / "docs" / "preview.html"

pytestmark = pytest.mark.skipif(not PREVIEW.exists(), reason="preview page not present")


@pytest.fixture(scope="module")
def page() -> str:
    return PREVIEW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def body(page: str) -> str:
    return page.split("<body>", 1)[1].split("<script>", 1)[0]


@pytest.fixture(scope="module")
def script(page: str) -> str:
    return page.split("<script>", 1)[1].split("</script>", 1)[0]


def test_no_duplicate_element_ids(body: str) -> None:
    ids = re.findall(r'\bid="([^"]+)"', body)
    dupes = {k: v for k, v in collections.Counter(ids).items() if v > 1}
    assert dupes == {}, (
        f"duplicate ids {dupes}: getElementById returns the first match, so a renderer "
        "writing to one of these silently overwrites the wrong element"
    )


def test_every_render_target_exists_exactly_once(body: str, script: str) -> None:
    ids = collections.Counter(re.findall(r'\bid="([^"]+)"', body))
    targets = set(re.findall(r'(?:fill|replace)\(\s*"([A-Za-z0-9_]+)"', script))
    targets |= set(re.findall(r'getElementById\(\s*"([A-Za-z0-9_]+)"', script))
    missing = sorted(t for t in targets if ids[t] == 0)
    ambiguous = sorted(t for t in targets if ids[t] > 1)
    assert missing == [], f"script writes to ids that do not exist: {missing}"
    assert ambiguous == [], f"script writes to duplicated ids: {ambiguous}"


def test_static_grid_containers_carry_their_layout_class(body: str) -> None:
    for cls, target in (
        ("career-grid", "careerGrid"),
        ("recruiter-grid", "recruiterGrid"),
        ("skill-grid", "skills"),
        ("specialisation-grid", "specialisations"),
        ("roadmap-grid", "roadmap"),
        ("parent-questions", "parentQuestions"),
    ):
        assert re.search(rf'class="{cls}" id="{target}"', body), (
            f"{cls} must sit on the element the renderer targets ({target}), "
            "otherwise cards stack vertically instead of forming a grid"
        )


def test_js_built_grids_are_created_with_their_class(script: str) -> None:
    for cls in ("subject-grid", "two-col"):
        assert f'"{cls}"' in script, f"{cls} is built in JS and must be given its layout class"


def test_section_anchors_survive_rendering(body: str, script: str) -> None:
    anchors = re.findall(r'href="#([a-z]+)"', body)
    for anchor in set(anchors):
        assert re.search(rf'<section[^>]*id="{anchor}"', body), f"nav links to #{anchor} with no section"
        assert not re.search(rf'(?:fill|replace)\(\s*"{anchor}"', script), (
            f"#{anchor} is a nav anchor; rendering into it would destroy the section heading"
        )
