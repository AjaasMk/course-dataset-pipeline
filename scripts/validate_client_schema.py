"""Validate course JSON against the client's own schema and validation rules.

Run: PYTHONPATH=. python scripts/validate_client_schema.py [dir]

The client supplied course-schema.json (shape), course-example.json (a filled
instance) and an implementation guide carrying explicit validation rules. This
checks any course JSON in that directory against both: structural conformance
to the schema, and the four rules the guide states.

Scores are reported, never rounded up: a file is READY only at 90 or above with
no errors, because the score is what decides whether it publishes.
"""

import json
import sys
from pathlib import Path

DEFAULT_DIR = Path("docs/specs by fmc/files")
SCHEMA_FILE = "course-schema.json"

# The four rules named in the request, plus the structural ones the schema
# itself implies. Each returns a list of error strings.
REQUIRED_SECTIONS = [
    "snapshot", "overview", "fit", "eligibility", "subjects", "skills",
    "careers", "recruiters", "pathway", "fees", "colleges", "compare",
    "nextSteps", "parentCorner", "faq",
]


def at(data, *path):
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def rule_quick_grid(course) -> list[str]:
    cards = at(course, "quickGrid", "cards")
    if not isinstance(cards, list):
        return ["quickGrid.cards missing or not a list"]
    if len(cards) != 6:
        return [f"quickGrid must have exactly 6 cards, found {len(cards)}"]
    return []


def rule_fit_score(course) -> list[str]:
    score = at(course, "hero", "fitPanel", "score")
    if score is None:
        return ["hero.fitPanel.score missing"]
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return [f"hero.fitPanel.score must be a number, found {type(score).__name__}"]
    if not 0 <= score <= 100:
        return [f"hero.fitPanel.score must be 0-100, found {score}"]
    return []


def rule_salary_values(course) -> list[str]:
    # salaryValues sits on a PANEL inside snapshot, not on snapshot itself --
    # the schema nests it under sections.snapshot.panels[]. Searching the panels
    # rather than assuming a flat path is what the client's own file requires.
    panels = at(course, "sections", "snapshot", "panels") or []
    values = next((p.get("salaryValues") for p in panels
                   if isinstance(p, dict) and "salaryValues" in p), None)
    if values is None:
        values = at(course, "sections", "snapshot", "salaryValues")
    if not isinstance(values, list):
        return ["salaryValues not found in sections.snapshot.panels[] or on snapshot"]
    if len(values) != 3:
        return [f"salaryValues must have exactly 3 items, found {len(values)}"]
    return []


def rule_fit_box_types(course) -> list[str]:
    boxes = at(course, "sections", "fit", "boxes")
    if not isinstance(boxes, list):
        return ["sections.fit.boxes missing or not a list"]
    allowed = {"positive", "caution"}
    bad = [b.get("type") for b in boxes
           if isinstance(b, dict) and b.get("type") not in allowed]
    if bad:
        return [f"fit.boxes[].type must be 'positive' or 'caution', found {bad}"]
    return []


def rule_no_empty_arrays(course) -> list[str]:
    errors = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list) and not node:
            errors.append(f"empty array at {path}")

    walk(course, "")
    return errors


def rule_sections_present(course) -> list[str]:
    sections = at(course, "sections") or {}
    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    return [f"missing sections: {', '.join(missing)}"] if missing else []


RULES = [
    ("quickGrid = exactly 6 cards", rule_quick_grid, 20),
    ("fitPanel.score is a number 0-100", rule_fit_score, 15),
    ("salaryValues = exactly 3 items", rule_salary_values, 15),
    ("fit.boxes[].type in {positive, caution}", rule_fit_box_types, 15),
    ("all 15 sections present", rule_sections_present, 20),
    ("no empty arrays", rule_no_empty_arrays, 15),
]


def validate(course: dict) -> tuple[int, list[str], list[dict]]:
    score, errors, detail = 0, [], []
    for label, rule, weight in RULES:
        found = rule(course)
        passed = not found
        score += weight if passed else 0
        errors.extend(found)
        detail.append({"rule": label, "weight": weight, "passed": passed,
                       "errors": found[:5]})
    return score, errors, detail


def status_for(score: int, errors: list[str]) -> str:
    if score >= 90 and not errors:
        return "READY"
    if score >= 60:
        return "NEEDS REVIEW"
    return "INVALID"


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    results = []

    for path in sorted(directory.glob("*.json")):
        if path.name == SCHEMA_FILE:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            results.append({"filename": path.name, "programTitle": "",
                            "validationScore": 0, "status": "INVALID",
                            "errors": [f"invalid JSON: {exc}"], "schema": {}})
            continue

        course = payload.get("course", payload)
        score, errors, detail = validate(course)
        results.append({
            "filename": path.name,
            "programTitle": at(course, "metadata", "title") or "",
            "validationScore": score,
            "status": status_for(score, errors),
            "errors": errors,
            "rules": detail,
            "schema": payload,
        })

    Path("data/verification").mkdir(parents=True, exist_ok=True)
    out = Path("data/verification/client_schema_validation.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'file':<26}{'title':<24}{'score':>6}  status")
    for r in results:
        print(f"{r['filename'][:24]:<26}{r['programTitle'][:22]:<24}"
              f"{r['validationScore']:>6}  {r['status']}")
        for rule in r.get("rules", []):
            if not rule["passed"]:
                print(f"      FAIL  {rule['rule']}")
                for err in rule["errors"]:
                    print(f"            {err[:88]}")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
