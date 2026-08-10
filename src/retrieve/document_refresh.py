import hashlib
from datetime import datetime, timezone
from typing import Optional, Union

import requests
from pydantic import BaseModel

from src.retrieve.base import REQUEST_TIMEOUT, USER_AGENT
from src.retrieve.models import DocumentRecord

# Client architecture spec's Document store risk control: "Immutable
# snapshots; page references; checksum; archive date." Checksum and
# archive date already exist (DocumentRecord.file_hash, .retrieved_at).
# What's missing: fetch_and_store() (src/retrieve/base.py) is idempotent
# on URL PRESENCE, not content -- once a URL has been fetched once, it is
# never re-checked, so a real content change at the same URL (AICTE
# revises a curriculum PDF, NIRF publishes a new year's ranking at the
# same page) goes undetected forever. Already anticipated but unbuilt --
# README's Stack section names "GitHub Actions (monthly re-crawl,
# hash-diffed)" as intended.
#
# Scoped to detection only. Fully solving "immutable snapshots" (every
# historical version preserved, independently addressable) would mean
# changing what document_id means -- right now it's a pure hash of the
# URL (base.py::document_id_for), used elsewhere as a stable lookup key
# (extraction's citation-labeling computes it straight from a chunk's
# source_url). Changing that to account for content-versioning is a
# bigger, separate decision, not made here.


class UpdateCheckResult(BaseModel):
    document_id: str
    document_url: str
    changed: bool
    old_hash: Optional[str]
    new_hash: str
    checked_at: str


def check_for_update(
    document: DocumentRecord,
    headers: Optional[dict] = None,
    verify: Union[str, bool] = True,
) -> UpdateCheckResult:
    """Re-fetch a previously stored document's URL and hash-compare against
    what was recorded. Does not overwrite anything -- purely a read-only
    check; the caller decides what to do with a detected change."""
    response = requests.get(
        document.document_url,
        headers=headers or {"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        verify=verify,
    )
    response.raise_for_status()
    new_hash = hashlib.sha256(response.content).hexdigest()

    return UpdateCheckResult(
        document_id=document.document_id,
        document_url=document.document_url,
        # No stored hash to diff against is new information, not a
        # confirmed match -- treated as changed rather than silently
        # assumed unchanged.
        changed=(document.file_hash is None or new_hash != document.file_hash),
        old_hash=document.file_hash,
        new_hash=new_hash,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
