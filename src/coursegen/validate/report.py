from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

Severity = Literal["error", "warning"]
Source = Literal["schema", "rule"]


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str
    severity: Severity = "error"
    source: Source = "rule"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
        }


@dataclass
class ValidationReport:
    scope: str
    course_id: str
    checked_at: str
    findings: list[Finding] = field(default_factory=list)
    skipped_rules: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def extend(self, findings: Iterable[Finding]) -> None:
        self.findings.extend(findings)

    def error_paths(self) -> set[str]:
        return {f.path for f in self.errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "pass" if self.passed else "fail",
            "scope": self.scope,
            "course_id": self.course_id,
            "checked_at": self.checked_at,
            "counts": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "skipped_rules": len(self.skipped_rules),
            },
            "findings": [f.to_dict() for f in self.findings],
            "skipped_rules": sorted(self.skipped_rules),
        }

    def feedback_lines(self, limit: int = 40) -> list[str]:
        return [
            f"- {f.path or '<root>'}: {f.message}"
            for f in self.errors[:limit]
        ]
