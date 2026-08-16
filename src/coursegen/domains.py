from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunks import CHUNKS, MAX_SEARCH_DOMAINS_PER_REQUEST, Chunk, normalize_domains

DEFAULT_KEY = "default"
ALL_CHUNKS_KEY = "_all"


class DomainRegistryError(RuntimeError):
    pass


def normalize_discipline(value: str | None) -> str:
    if not value:
        return ""
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in cleaned.split("-") if part)


@dataclass(frozen=True)
class ResolvedDomains:
    discipline: str
    chunk_key: str
    domains: tuple[str, ...]
    layers: tuple[str, ...]
    dropped: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "discipline": self.discipline or None,
            "chunk": self.chunk_key,
            "domains": list(self.domains),
            "count": len(self.domains),
            "layers_used": list(self.layers),
            "dropped_over_cap": list(self.dropped),
        }


@dataclass(frozen=True)
class DomainRegistry:
    table: dict[str, dict[str, tuple[str, ...]]]

    @classmethod
    def empty(cls) -> DomainRegistry:
        return cls(table={})

    @classmethod
    def load(cls, path: Path | None) -> DomainRegistry:
        if path is None or not Path(path).exists():
            return cls.empty()
        try:
            with Path(path).open(encoding="utf-8") as handle:
                raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise DomainRegistryError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise DomainRegistryError(f"{path} must hold a JSON object at the top level")

        known_chunks = {chunk.key for chunk in CHUNKS} | {ALL_CHUNKS_KEY}
        table: dict[str, dict[str, tuple[str, ...]]] = {}
        for discipline, groups in raw.items():
            if not isinstance(groups, dict):
                raise DomainRegistryError(f"{path}: entry {discipline!r} must be an object")
            key = DEFAULT_KEY if discipline == DEFAULT_KEY else normalize_discipline(discipline)
            bucket: dict[str, tuple[str, ...]] = {}
            for chunk_key, values in groups.items():
                if chunk_key not in known_chunks:
                    raise DomainRegistryError(
                        f"{path}: {discipline!r} names unknown chunk {chunk_key!r}; "
                        f"expected one of {sorted(known_chunks)}"
                    )
                if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                    raise DomainRegistryError(
                        f"{path}: {discipline!r}.{chunk_key} must be a list of strings"
                    )
                bucket[chunk_key] = normalize_domains(tuple(values))
            table[key] = bucket
        return cls(table=table)

    def disciplines(self) -> list[str]:
        return sorted(key for key in self.table if key != DEFAULT_KEY)

    def _layer(self, discipline: str, chunk_key: str) -> tuple[str, ...]:
        return self.table.get(discipline, {}).get(chunk_key, ())

    def resolve(
        self,
        discipline: str | None,
        chunk: Chunk,
        fallback: tuple[str, ...],
        *,
        cap: int = MAX_SEARCH_DOMAINS_PER_REQUEST,
    ) -> ResolvedDomains:
        key = normalize_discipline(discipline)
        sources: list[tuple[str, tuple[str, ...]]] = [
            (f"{key}.{chunk.key}", self._layer(key, chunk.key) if key else ()),
            (f"{key}._all", self._layer(key, ALL_CHUNKS_KEY) if key else ()),
            (f"default.{chunk.key}", self._layer(DEFAULT_KEY, chunk.key)),
            ("default._all", self._layer(DEFAULT_KEY, ALL_CHUNKS_KEY)),
            ("chunks.py", normalize_domains(chunk.domains)),
            ("SEARCH_DOMAINS", normalize_domains(fallback)),
        ]

        ordered: list[str] = []
        layers: list[str] = []
        for label, values in sources:
            used = False
            for domain in values:
                if domain not in ordered:
                    ordered.append(domain)
                    used = True
            if used:
                layers.append(label)

        excluded = {domain[1:] for domain in ordered if domain.startswith("-")}
        ordered = [d for d in ordered if not (not d.startswith("-") and d in excluded)]

        kept = tuple(ordered[:cap])
        dropped = tuple(ordered[cap:])
        return ResolvedDomains(
            discipline=key,
            chunk_key=chunk.key,
            domains=kept,
            layers=tuple(layers),
            dropped=dropped,
        )

    def allowlist(self, fallback: tuple[str, ...]) -> tuple[str, ...]:
        merged: list[str] = []
        groups = [normalize_domains(fallback)]
        groups.extend(normalize_domains(chunk.domains) for chunk in CHUNKS)
        for bucket in self.table.values():
            groups.extend(bucket.values())
        for group in groups:
            for domain in group:
                if not domain.startswith("-") and domain not in merged:
                    merged.append(domain)
        return tuple(merged)
