import pickle
from dotenv import load_dotenv

load_dotenv()

import anthropic

from src.courses.taxonomy import load_taxonomy
from src.extract.facts_extraction import extract_course
from src.facts.course_facts import COURSE_FIELD_IDS
from src.facts.course_store import current_course, record_course

with open("data/tmp_mech_chunks.pkl", "rb") as f:
    chunks = pickle.load(f)

taxonomy = load_taxonomy()
course = next(c for c in taxonomy if c.standard_course_name == "Mechanical Engineering")

client = anthropic.Anthropic()
result, refs = extract_course(chunks, course, client=client)

if result is None:
    print("no Course Identity / Duration & Mode chunks found -- nothing to extract")
    raise SystemExit(1)

print("=== extracted Course ===")
print(result.model_dump_json(indent=2))
print()
print("=== citations ===")
for r in refs:
    field_name = next(k for k, v in COURSE_FIELD_IDS.items() if v == r.field_id)
    print(f"  {r.field_id} ({field_name}) <- {r.document_id}: {r.quoted_evidence[:80]!r}")

record_id = record_course(result, refs)
print()
print("recorded:", record_id)

round_tripped = current_course(course.course_id)
print()
print("=== round-tripped from store ===")
print(round_tripped.model_dump_json(indent=2))
assert round_tripped.standard_course_name == result.standard_course_name
assert round_tripped.semester_count == result.semester_count
print()
print("OK -- round-trip matches")
