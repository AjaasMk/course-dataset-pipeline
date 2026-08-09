from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from src.retrieve.models import IntentRole, RetrievalIntent, SourceTier

DEFAULT_SOURCES_PATH = Path("config/sources.yaml")

_CANONICAL_ROLES = (IntentRole.PRIMARY, IntentRole.SECONDARY)
_NON_CANONICAL_TIERS = (SourceTier.D, SourceTier.E, SourceTier.F)


class SourceAuthorityError(Exception):
    pass


class Source(BaseModel):
    source_id: str
    name: str
    official_url: str
    authority_type: str
    tiers: list[SourceTier]
    coverage: str
    status: str
    listing_page: Optional[str] = None
    match_threshold: Optional[float] = None


class SourceRegistry(BaseModel):
    sources: dict[str, Source]
    regulator_map: dict[str, dict]
    segment_sources: dict[str, dict]
    threshold: float

    def tiers_for(self, source_id: str) -> list[SourceTier]:
        source = self.sources.get(source_id)
        if source is None:
            raise SourceAuthorityError(f"unknown source_id {source_id!r}")
        return source.tiers

    def best_tier(self, source_id: str) -> SourceTier:
        return min(self.tiers_for(source_id), key=lambda t: t.value)

    def threshold_for(self, source_id: str) -> float:
        source = self.sources.get(source_id)
        if source is None:
            raise SourceAuthorityError(f"unknown source_id {source_id!r}")
        return self.threshold if source.match_threshold is None else source.match_threshold

    def validate_intent(self, intent: RetrievalIntent) -> None:
        tiers = self.tiers_for(intent.source_id)
        if intent.role in _CANONICAL_ROLES and all(t in _NON_CANONICAL_TIERS for t in tiers):
            raise SourceAuthorityError(
                f"{intent.source_id!r} is tier "
                f"{'/'.join(t.value for t in tiers)} and may only hold a discovery role, "
                f"not {intent.role.value!r} — it can never be canonical without "
                f"Tier A/B/C corroboration"
            )

    def unknown_regulator_map_references(self) -> list[str]:
        referenced: list[str] = []
        for area in self.regulator_map.values():
            referenced.append(area["primary"])
            referenced.extend(area.get("secondary") or [])
        return sorted({r for r in referenced if r not in self.sources})

    def unknown_segment_source_references(self) -> list[str]:
        referenced: list[str] = []
        for segment in self.segment_sources.values():
            referenced.extend(segment.get("preferred") or [])
            referenced.extend(segment.get("secondary") or [])
        return sorted({r for r in referenced if r not in self.sources})


def load_registry(path: Optional[Path] = None) -> SourceRegistry:
    resolved = path if path is not None else DEFAULT_SOURCES_PATH
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))

    sources = {
        source_id: Source(source_id=source_id, **body)
        for source_id, body in raw["sources"].items()
    }
    return SourceRegistry(
        sources=sources,
        regulator_map=raw["regulator_map"],
        segment_sources=raw["segment_sources"],
        threshold=raw["matching"]["threshold"],
    )
