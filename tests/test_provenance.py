from datetime import datetime, timezone

from src.facts.course_facts import Curriculum, CURRICULUM_FIELD_IDS
from src.facts.course_store import record_curriculum
from src.facts.engine import field_ref
from src.facts.models import VerificationStatus
from src.facts.provenance import ProvenanceRecord, provenance_for
from src.retrieve.models import DocumentRecord, SourceTier
from src.retrieve.store import insert_document


def _document(**overrides):
    fields = {
        "document_id": "DOC-aicte-mech",
        "source_id": "AICTE",
        "source_tier": SourceTier.A,
        "document_url": "https://www.aicte.gov.in/sites/default/files/Final_Mechanical Engg.pdf",
        "document_title": "Revised Model Curriculum for UG Degree Course in Mechanical Engineering",
        "publication_date": "2024-01-15",
        "valid_from": "2024-01-15",
        "valid_until": None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    fields.update(overrides)
    return DocumentRecord(**fields)


def _curriculum_with_refs(course_id="mechanical_engineering"):
    curriculum = Curriculum(
        course_id=course_id, curriculum_year="2024",
        foundation_subjects=["Mathematics", "Physics"],
    )
    refs = [
        field_ref(
            CURRICULUM_FIELD_IDS["foundation_subjects"], "DOC-aicte-mech",
            "Mathematics, Physics", VerificationStatus.HUMAN_VERIFIED,
        )
    ]
    return curriculum, refs


def test_provenance_joins_citation_with_real_document_metadata(tmp_path):
    documents_db = tmp_path / "manifest.db"
    facts_db = tmp_path / "facts.db"
    insert_document(_document(), db_path=documents_db)

    curriculum, refs = _curriculum_with_refs()
    record_id = record_curriculum(curriculum, refs, db_path=facts_db)

    records = provenance_for("curricula", record_id, facts_db_path=facts_db, documents_db_path=documents_db)

    assert len(records) == 1
    record = records[0]
    assert isinstance(record, ProvenanceRecord)
    assert record.source_id == "AICTE"
    assert record.source_tier == SourceTier.A
    assert record.document_url == _document().document_url
    assert record.publication_date == "2024-01-15"
    assert record.quoted_evidence == "Mathematics, Physics"
    assert record.verification_status == VerificationStatus.HUMAN_VERIFIED
    assert record.field_id == CURRICULUM_FIELD_IDS["foundation_subjects"]


def test_provenance_skips_a_ref_whose_document_no_longer_exists(tmp_path):
    # A ref pointing at a document_id absent from the documents table is a
    # real data-integrity signal, not something to fabricate metadata for --
    # skipped (with a warning logged), not raised, so one broken citation
    # doesn't take down a whole provenance lookup.
    documents_db = tmp_path / "manifest.db"
    facts_db = tmp_path / "facts.db"
    # deliberately do NOT insert the document this time

    curriculum, refs = _curriculum_with_refs()
    record_id = record_curriculum(curriculum, refs, db_path=facts_db)

    records = provenance_for("curricula", record_id, facts_db_path=facts_db, documents_db_path=documents_db)

    assert records == []


def test_provenance_returns_empty_list_for_a_record_with_no_refs(tmp_path):
    documents_db = tmp_path / "manifest.db"
    facts_db = tmp_path / "facts.db"

    records = provenance_for("curricula", "REC-nonexistent", facts_db_path=facts_db, documents_db_path=documents_db)

    assert records == []


def test_provenance_records_can_be_ranked_by_tier(tmp_path):
    documents_db = tmp_path / "manifest.db"
    facts_db = tmp_path / "facts.db"
    insert_document(_document(source_id="AICTE", source_tier=SourceTier.A), db_path=documents_db)
    insert_document(
        _document(
            document_id="DOC-careers360", source_id="CAREERS360", source_tier=SourceTier.D,
            document_url="https://www.careers360.com/mech",
        ),
        db_path=documents_db,
    )

    curriculum = Curriculum(course_id="mechanical_engineering", curriculum_year="2024", core_subjects=["Thermodynamics"])
    refs = [
        field_ref(CURRICULUM_FIELD_IDS["core_subjects"], "DOC-careers360", "Thermodynamics is core"),
    ]
    record_id = record_curriculum(curriculum, refs, db_path=facts_db)

    records = provenance_for("curricula", record_id, facts_db_path=facts_db, documents_db_path=documents_db)
    ranked = sorted(records, key=lambda r: r.source_tier.value)

    assert ranked[0].source_tier == SourceTier.D  # only one ref in this record -- sanity-checks the sort key works
