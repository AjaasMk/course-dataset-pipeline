import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, Union

import requests

from src.retrieve import store
from src.retrieve.models import (
    DiscoveredDocument,
    DocumentRecord,
    DocumentType,
    RetrievalIntent,
    SourceTier,
)

USER_AGENT = "course-dataset-pipeline/0.1 (educational course dataset project)"
REQUEST_TIMEOUT = 15

_PDF_SUFFIX = ".pdf"


def document_id_for(url: str) -> str:
    return f"DOC-{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def document_type_of(url: str) -> DocumentType:
    return (
        DocumentType.OFFICIAL_PDF
        if url.lower().split("?")[0].endswith(_PDF_SUFFIX)
        else DocumentType.OFFICIAL_WEBPAGE
    )


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# Windows NTFS (and most filesystems) cap an individual filename component
# around 255 chars; some real document titles run well past that (a real
# NAPS/NSP title hit ~280 chars, confirmed live to crash write_bytes() with
# [Errno 22] Invalid argument). 150 leaves headroom for the extension and
# the disambiguating hash suffix below, comfortably under any real limit.
_MAX_SLUG_LENGTH = 150
_TITLE_HASH_LENGTH = 8


def _safe_filename(title: str, extension: str) -> str:
    slug = slugify(title)
    if len(slug) <= _MAX_SLUG_LENGTH:
        return f"{slug}.{extension}"
    # A hash of the FULL original title, not just the truncated slug --
    # two different overlong titles that happen to share the same first
    # _MAX_SLUG_LENGTH chars must not collide onto the same file.
    suffix = hashlib.sha256(title.encode()).hexdigest()[:_TITLE_HASH_LENGTH]
    return f"{slug[:_MAX_SLUG_LENGTH]}_{suffix}.{extension}"


def fetch_and_store(
    document: DiscoveredDocument,
    source_id: str,
    source_tier: SourceTier,
    raw_dir: Path,
    extension: str,
    headers: Optional[dict] = None,
    verify: Union[str, bool] = True,
) -> DocumentRecord:
    existing = store.get_document_by_url(document.document_url)
    if existing is not None:
        return existing

    response = requests.get(
        document.document_url,
        headers=headers or {"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        verify=verify,
    )
    response.raise_for_status()

    local_path = raw_dir / source_id / _safe_filename(document.document_title, extension)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(response.content)

    content_length = response.headers.get("Content-Length")
    record = DocumentRecord(
        document_id=document_id_for(document.document_url),
        source_id=source_id,
        source_tier=source_tier,
        document_url=document.document_url,
        document_title=document.document_title,
        local_path=str(local_path),
        file_hash=hashlib.sha256(response.content).hexdigest(),
        content_type=response.headers.get("Content-Type"),
        content_length=int(content_length) if content_length is not None else None,
        http_status=response.status_code,
        publication_date=document.publication_date,
        academic_year=document.academic_year,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    store.insert_document(record)
    return record


class SourceAdapter(Protocol):
    source_id: str
    tiers: list[SourceTier]

    def supports(self, intent: RetrievalIntent) -> bool:
        """Whether this adapter can serve the intent at all."""
        ...

    def resolve(self, intent: RetrievalIntent) -> list[DiscoveredDocument]:
        """Discover real documents for the intent, best candidate first.

        Returns every plausible candidate rather than a single winner —
        applying a confidence threshold, and deciding whether the result is
        good enough, is the caller's job. An empty list means the source has
        nothing for this intent, which is a valid outcome.
        """
        ...

    def download(self, document: DiscoveredDocument) -> DocumentRecord:
        """Fetch, hash, store and record the document.

        Idempotent on document_url: an already-stored document is returned
        without making an HTTP request.
        """
        ...
