from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jsonschema import Draft202012Validator

from .report import Finding, ValidationReport
from .rules import ALL_RULES, Rule, RuleContext, has_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_pointer(path: Any) -> str:
    parts: list[str] = []
    for item in path:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}" if parts else str(item))
    return "".join(parts)


def schema_findings(document: dict[str, Any], schema: dict[str, Any]) -> list[Finding]:
    validator = Draft202012Validator(schema)
    findings: list[Finding] = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        findings.append(
            Finding(
                code=str(error.validator),
                path=_json_pointer(error.absolute_path),
                message=error.message,
                severity="error",
                source="schema",
            )
        )
    return findings


def rule_findings(
    document: dict[str, Any],
    context: RuleContext,
    rules: tuple[Rule, ...] = ALL_RULES,
) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    skipped: list[str] = []
    for rule in rules:
        if any(not has_path(document, required) for required in rule.requires):
            skipped.append(rule.code)
            continue
        findings.extend(rule.fn(document, context))
    return findings, skipped


def validate_document(
    document: dict[str, Any],
    schema: dict[str, Any],
    context: RuleContext,
    *,
    scope: str = "document",
    course_id: str = "",
    rules: tuple[Rule, ...] = ALL_RULES,
) -> ValidationReport:
    report = ValidationReport(
        scope=scope,
        course_id=course_id or str(document.get("course_id", "")),
        checked_at=_now(),
    )
    report.extend(schema_findings(document, schema))
    found, skipped = rule_findings(document, context, rules)
    report.extend(found)
    report.skipped_rules = skipped
    return report
