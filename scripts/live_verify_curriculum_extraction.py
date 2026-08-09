import pickle
from dotenv import load_dotenv

load_dotenv()

import anthropic

from src.courses.taxonomy import load_taxonomy
from src.extract.facts_extraction import extract_curriculum
from src.facts.course_facts import CURRICULUM_FIELD_IDS
from src.facts.course_store import current_curriculum, record_curriculum

with open("data/tmp_mech_chunks.pkl", "rb") as f:
    chunks = pickle.load(f)

taxonomy = load_taxonomy()
course = next(c for c in taxonomy if c.standard_course_name == "Mechanical Engineering")

client = anthropic.Anthropic()
curriculum, refs = extract_curriculum(chunks, course, "2024", client=client)

print("=== extracted Curriculum ===")
print(curriculum.model_dump_json(indent=2))
print()
print("=== citations ===")
for r in refs:
    field_name = next(k for k, v in CURRICULUM_FIELD_IDS.items() if v == r.field_id)
    print(f"  {r.field_id} ({field_name}) <- {r.document_id}: {r.quoted_evidence[:80]!r}")

record_id = record_curriculum(curriculum, refs)
print()
print("recorded:", record_id)

round_tripped = current_curriculum(course.course_id, "2024")
print()
print("=== round-tripped from store ===")
print(round_tripped.model_dump_json(indent=2))
assert round_tripped.foundation_subjects == curriculum.foundation_subjects
assert round_tripped.core_subjects == curriculum.core_subjects
print()
print("OK -- round-trip matches")
