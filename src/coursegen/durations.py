from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_ACADEMIC_YEARS = 5


class DurationRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Duration:
    min_years: float
    max_years: float
    academic_years: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_years": self.min_years,
            "max_years": self.max_years,
            "academic_years": self.academic_years,
            "source": self.source,
        }

    def typical_duration(self) -> dict[str, float]:
        return {"min_years": self.min_years, "max_years": self.max_years}


def normalize_course_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def academic_years_from_duration(min_years: float, max_years: float) -> int:
    return max(math.floor(min_years), min(math.ceil(max_years), MAX_ACADEMIC_YEARS))


def _entry(raw: Any, source: str, label: str) -> Duration:
    if not isinstance(raw, dict):
        raise DurationRegistryError(f"{label} must be an object, got {type(raw).__name__}")
    try:
        low = float(raw["min_years"])
        high = float(raw["max_years"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DurationRegistryError(f"{label} needs numeric min_years and max_years") from exc
    if low <= 0 or high < low:
        raise DurationRegistryError(f"{label} has an impossible span {low}-{high}")
    years = raw.get("academic_years")
    if years is None:
        years = academic_years_from_duration(low, high)
    if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= MAX_ACADEMIC_YEARS:
        raise DurationRegistryError(
            f"{label} academic_years must be an integer 1..{MAX_ACADEMIC_YEARS}, got {years!r}"
        )
    if years > math.ceil(high):
        raise DurationRegistryError(
            f"{label} shows {years} taught years but the programme runs {high}"
        )
    return Duration(min_years=low, max_years=high, academic_years=years, source=source)


@dataclass(frozen=True)
class DurationRegistry:
    exact: dict[str, Duration]
    patterns: tuple[tuple[re.Pattern[str], Duration], ...]

    @classmethod
    def empty(cls) -> DurationRegistry:
        return cls(exact={}, patterns=())

    @classmethod
    def load(cls, path: Path | str | None) -> DurationRegistry:
        if path is None or not Path(path).exists():
            return cls.empty()
        try:
            with Path(path).open(encoding="utf-8") as handle:
                raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise DurationRegistryError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise DurationRegistryError(f"{path} must hold an object")

        exact: dict[str, Duration] = {}
        for name, value in (raw.get("exact") or {}).items():
            key = normalize_course_name(name)
            if key in exact:
                raise DurationRegistryError(f"{path} lists {name!r} twice")
            exact[key] = _entry(value, f"exact:{key}", f"{path}: exact[{name!r}]")

        patterns: list[tuple[re.Pattern[str], Duration]] = []
        for index, rule in enumerate(raw.get("patterns") or []):
            label = f"{path}: patterns[{index}]"
            if not isinstance(rule, dict) or "match" not in rule:
                raise DurationRegistryError(f"{label} needs a 'match' expression")
            expression = str(rule["match"])
            if any(ord(char) < 32 for char in expression):
                raise DurationRegistryError(f"{label} contains a control character: {expression!r}")
            try:
                compiled = re.compile(expression)
            except re.error as exc:
                raise DurationRegistryError(f"{label} is not a valid expression: {exc}") from exc
            patterns.append((compiled, _entry(rule, f"pattern:{expression}", label)))

        return cls(exact=exact, patterns=tuple(patterns))

    def resolve(self, course_name: str) -> Duration | None:
        key = normalize_course_name(course_name)
        if not key:
            return None
        found = self.exact.get(key)
        if found is not None:
            return found
        for compiled, duration in self.patterns:
            if compiled.search(key):
                return duration
        return None
