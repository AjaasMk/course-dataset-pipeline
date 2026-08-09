import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel, Field

from src.retrieve import store
from src.retrieve.models import (
    IntentResolution,
    IntentRole,
    RetrievalIntent,
    RetrievalStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.80

_CANONICAL_ROLES = (IntentRole.PRIMARY, IntentRole.SECONDARY)


class Adapter(Protocol):
    source_id: str
    tiers: list

    def supports(self, intent: RetrievalIntent) -> bool: ...
    def resolve(self, intent: RetrievalIntent) -> list: ...
    def download(self, document) -> object: ...


class ResolutionReport(BaseModel):
    intents: int = 0
    resolved: int = 0
    resolved_authoritative: int = 0
    resolved_secondary: int = 0
    unresolved: int = 0
    errored: int = 0
    documents: int = 0
    by_segment_tier: dict[tuple[str, str], dict[str, int]] = Field(default_factory=dict)
    reasons: dict[str, int] = Field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.errored:
            return "partial"
        return "pass" if self.resolved else "unresolved"


def _record(report: ResolutionReport, segment: str, tier: str, status: RetrievalStatus) -> None:
    bucket = report.by_segment_tier.setdefault((segment, tier), defaultdict(int))
    bucket[status.value] += 1


def _tier_of(source_id: str, tiers: dict, adapter) -> str:
    # Tier belongs to the source, not the adapter. Reading it from the adapter
    # loses stratification for precisely the intents no adapter served.
    declared = tiers.get(source_id)
    if declared:
        found = declared if isinstance(declared, (list, tuple)) else [declared]
        return min(t.value for t in found)
    from_adapter = getattr(adapter, "tiers", None)
    return min(t.value for t in from_adapter) if from_adapter else "?"


def resolve_intents(
    intents: list[RetrievalIntent],
    adapters: dict[str, Adapter],
    thresholds: Optional[dict[str, float]] = None,
    tiers: Optional[dict] = None,
    db_path: Optional[Path] = None,
) -> ResolutionReport:
    thresholds = thresholds or {}
    tiers = tiers or {}
    report = ResolutionReport(intents=len(intents))

    for intent in intents:
        store.insert_intent(intent, db_path=db_path)
        adapter = adapters.get(intent.source_id)
        segment = intent.segment.value

        tier = _tier_of(intent.source_id, tiers, adapter)

        if adapter is None or not adapter.supports(intent):
            report.unresolved += 1
            report.reasons["no_adapter"] = report.reasons.get("no_adapter", 0) + 1
            _record(report, segment, tier, RetrievalStatus.UNRESOLVED)
            continue
        try:
            discovered = adapter.resolve(intent)
        except Exception as exc:
            # One unreachable source must not abort a 23,000-intent run.
            logger.warning("resolve failed for %s: %s", intent.intent_id, exc)
            report.errored += 1
            report.reasons[type(exc).__name__] = report.reasons.get(type(exc).__name__, 0) + 1
            _record(report, segment, tier, RetrievalStatus.UNRESOLVED)
            continue

        threshold = thresholds.get(intent.source_id, DEFAULT_THRESHOLD)
        accepted = [d for d in discovered if d.match_confidence >= threshold]
        if not accepted:
            report.unresolved += 1
            best = max((d.match_confidence for d in discovered), default=0.0)
            reason = "below_threshold" if discovered else "nothing_discovered"
            report.reasons[reason] = report.reasons.get(reason, 0) + 1
            logger.info("%s unresolved: best %.2f < %.2f", intent.intent_id, best, threshold)
            _record(report, segment, tier, RetrievalStatus.UNRESOLVED)
            continue

        for document in accepted:
            try:
                record = adapter.download(document)
            except Exception as exc:
                logger.warning("download failed for %s: %s", document.document_url, exc)
                report.errored += 1
                report.reasons[type(exc).__name__] = report.reasons.get(type(exc).__name__, 0) + 1
                continue

            # The resolver owns db_path, so it persists the record rather than
            # relying on the adapter having written to a module-level default.
            # Real adapters also insert during fetch; that write is INSERT OR
            # IGNORE on a unique document_url, so the repeat is harmless.
            store.insert_document(record, db_path=db_path)
            store.insert_resolution(
                IntentResolution(
                    intent_id=intent.intent_id,
                    document_id=record.document_id,
                    match_confidence=document.match_confidence,
                    match_type=document.match_type,
                    validated=True,
                ),
                db_path=db_path,
            )

        # A Tier D source clearing threshold is corroboration, never a canonical
        # answer -- the role decides that, not the score.
        authoritative = intent.role in _CANONICAL_ROLES
        status = (
            RetrievalStatus.AUTHORITATIVE_SOURCE_FOUND
            if authoritative
            else RetrievalStatus.SECONDARY_SOURCE_FOUND
        )
        report.resolved += 1
        if authoritative:
            report.resolved_authoritative += 1
        else:
            report.resolved_secondary += 1
        _record(report, segment, tier, status)

    report.documents = store.count_documents(db_path=db_path)
    return report
