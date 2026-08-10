import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.facts.course_store import refs_for
from src.facts.models import VerificationStatus
from src.retrieve.models import SourceTier
from src.retrieve.store import get_document_by_id

logger = logging.getLogger(__name__)


class ProvenanceRecord(BaseModel):
    """Client architecture spec's 'Source registry' layer: provenance and
    verification state as one queryable row per citation -- source ID,
    tier, URL, publication date, validity, page, evidence, reviewer.

    Not a new table: a join over what already exists correctly in two
    places -- src/retrieve/store.py's documents table (source-level
    metadata: tier, URL, validity) and src/facts/engine.py's
    course_fact_refs table (citation-level: evidence, page, reviewer).
    Duplicating that data into a third table risks the two falling out of
    sync; joining them at query time can't.

    Distinct from src/retrieve/registry.py::SourceRegistry, which is the
    static config of the 44 named, authorized sources (which sources
    exist, what tier, what URL) loaded from config/sources.yaml -- that's
    the design-time half of "source registry." This is the runtime half:
    the actual evidence trail behind one specific extracted fact.
    """

    field_id: str
    document_id: str
    source_id: str
    source_tier: SourceTier
    document_url: str
    document_title: str
    publication_date: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    page_number: Optional[str] = None
    quoted_evidence: str
    verification_status: VerificationStatus
    reviewed_by: Optional[str] = None


def provenance_for(
    fact_table: str,
    record_id: str,
    facts_db_path: Optional[Path] = None,
    documents_db_path: Optional[Path] = None,
) -> list[ProvenanceRecord]:
    """The full provenance trail for one fact record: every citation, each
    joined with its source document's tier/URL/validity. Best-effort, not
    all-or-nothing -- a ref whose document has since disappeared from the
    documents table is a real data-integrity signal worth logging, but one
    broken citation must not take down a lookup for the rest."""
    refs = refs_for(fact_table, record_id, db_path=facts_db_path)
    records: list[ProvenanceRecord] = []
    for ref in refs:
        document = get_document_by_id(ref.document_id, db_path=documents_db_path)
        if document is None:
            logger.warning(
                "provenance: %s field %s cites document_id %s, which has no matching document record",
                fact_table, ref.field_id, ref.document_id,
            )
            continue
        records.append(
            ProvenanceRecord(
                field_id=ref.field_id,
                document_id=ref.document_id,
                source_id=document.source_id,
                source_tier=document.source_tier,
                document_url=document.document_url,
                document_title=document.document_title,
                publication_date=document.publication_date,
                valid_from=document.valid_from,
                valid_until=document.valid_until,
                page_number=ref.page_number,
                quoted_evidence=ref.quoted_evidence,
                verification_status=ref.verification_status,
                reviewed_by=ref.reviewed_by,
            )
        )
    return records
