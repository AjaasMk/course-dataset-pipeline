from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from coursegen.chunks import CHUNKS_BY_KEY, MAX_SEARCH_DOMAINS_PER_REQUEST
from coursegen.config import Settings
from coursegen.domains import DomainRegistry, DomainRegistryError, normalize_discipline
from coursegen.generate import generate_course

from test_generate import COURSE_CATEGORY, COURSE_ID, COURSE_NAME, FakeClient, chunk_payload

MARKET = CHUNKS_BY_KEY["market"]
ACADEMICS = CHUNKS_BY_KEY["academics"]


def write_registry(tmp_path: Path, table: dict[str, Any]) -> Path:
    path = tmp_path / "domains.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    return path


def test_missing_file_yields_empty_registry(tmp_path: Path) -> None:
    registry = DomainRegistry.load(tmp_path / "nope.json")
    assert registry.disciplines() == []
    assert registry.resolve("engineering", MARKET, ("ugc.gov.in",)).domains == ("ugc.gov.in",)


def test_discipline_chunk_beats_discipline_all_beats_default(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "default": {"_all": ["ugc.gov.in"], "market": ["nirfindia.org"]},
            "engineering": {"_all": ["aicte-india.org"], "market": ["josaa.nic.in"]},
        },
    )
    registry = DomainRegistry.load(path)
    resolved = registry.resolve("engineering", MARKET, ())
    assert resolved.domains == ("josaa.nic.in", "aicte-india.org", "nirfindia.org", "ugc.gov.in")
    assert resolved.layers == ("engineering.market", "engineering._all", "default.market", "default._all")


def test_discipline_without_chunk_entry_falls_through(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "default": {"_all": ["ugc.gov.in"], "market": ["nirfindia.org"]},
            "law": {"_all": ["barcouncilofindia.org"]},
        },
    )
    registry = DomainRegistry.load(path)
    assert registry.resolve("law", MARKET, ()).domains == (
        "barcouncilofindia.org",
        "nirfindia.org",
        "ugc.gov.in",
    )


def test_unknown_discipline_uses_default_only(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {"default": {"_all": ["ugc.gov.in"]}, "engineering": {"_all": ["aicte-india.org"]}},
    )
    registry = DomainRegistry.load(path)
    assert registry.resolve("underwater-basket-weaving", MARKET, ()).domains == ("ugc.gov.in",)


def test_no_discipline_uses_default_only(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {"default": {"_all": ["ugc.gov.in"]}, "engineering": {"_all": ["aicte-india.org"]}},
    )
    registry = DomainRegistry.load(path)
    assert registry.resolve(None, MARKET, ()).domains == ("ugc.gov.in",)


def test_disciplines_do_not_leak_into_each_other(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "engineering": {"market": ["josaa.nic.in"]},
            "medicine-pharmacy": {"market": ["mcc.nic.in"]},
        },
    )
    registry = DomainRegistry.load(path)
    assert registry.resolve("engineering", MARKET, ()).domains == ("josaa.nic.in",)
    assert registry.resolve("medicine-pharmacy", MARKET, ()).domains == ("mcc.nic.in",)


def test_chunks_differ_within_one_discipline(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {"engineering": {"market": ["josaa.nic.in"], "academics": ["aicte-india.org"]}},
    )
    registry = DomainRegistry.load(path)
    assert registry.resolve("engineering", MARKET, ()).domains == ("josaa.nic.in",)
    assert registry.resolve("engineering", ACADEMICS, ()).domains == ("aicte-india.org",)


def test_resolution_is_capped_and_reports_what_it_dropped(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "engineering": {"market": [f"e{i}.example.gov" for i in range(16)]},
            "default": {"_all": [f"d{i}.example.gov" for i in range(8)]},
        },
    )
    registry = DomainRegistry.load(path)
    resolved = registry.resolve("engineering", MARKET, ())
    assert len(resolved.domains) == MAX_SEARCH_DOMAINS_PER_REQUEST == 20
    assert resolved.domains[:16] == tuple(f"e{i}.example.gov" for i in range(16))
    assert resolved.dropped == tuple(f"d{i}.example.gov" for i in range(4, 8))


def test_urls_in_the_registry_are_normalised(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path, {"engineering": {"market": ["https://www.nirfindia.org/Rankings/2026/"]}}
    )
    assert DomainRegistry.load(path).resolve("engineering", MARKET, ()).domains == ("nirfindia.org",)


def test_exclusion_removes_an_inherited_domain(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "default": {"_all": ["ugc.gov.in", "quora.com"]},
            "engineering": {"market": ["-quora.com"]},
        },
    )
    resolved = DomainRegistry.load(path).resolve("engineering", MARKET, ())
    assert "quora.com" not in resolved.domains
    assert "-quora.com" in resolved.domains


def test_allowlist_spans_every_discipline(tmp_path: Path) -> None:
    path = write_registry(
        tmp_path,
        {
            "default": {"_all": ["ugc.gov.in"]},
            "engineering": {"market": ["josaa.nic.in", "-quora.com"]},
            "law": {"_all": ["barcouncilofindia.org"]},
        },
    )
    allowlist = DomainRegistry.load(path).allowlist(())
    assert set(allowlist) == {"ugc.gov.in", "josaa.nic.in", "barcouncilofindia.org"}


def test_unknown_chunk_key_in_file_is_rejected(tmp_path: Path) -> None:
    path = write_registry(tmp_path, {"engineering": {"colleges": ["nirfindia.org"]}})
    with pytest.raises(DomainRegistryError, match="unknown chunk"):
        DomainRegistry.load(path)


def test_malformed_registry_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "domains.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DomainRegistryError, match="not valid JSON"):
        DomainRegistry.load(path)

    path.write_text(json.dumps({"engineering": {"market": "nirfindia.org"}}), encoding="utf-8")
    with pytest.raises(DomainRegistryError, match="list of strings"):
        DomainRegistry.load(path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Engineering", "engineering"),
        ("Medicine & Pharmacy", "medicine-pharmacy"),
        ("  Arts / Humanities  ", "arts-humanities"),
        (None, ""),
    ],
)
def test_discipline_keys_are_normalised(raw: str | None, expected: str) -> None:
    assert normalize_discipline(raw) == expected


def test_shipped_registry_file_loads(domains_path: Path) -> None:
    registry = DomainRegistry.load(domains_path)
    assert len(registry.disciplines()) == 16
    assert "engineering-technology" in registry.disciplines()
    assert "medical-allied-health" in registry.disciplines()


def test_discipline_reaches_the_request(
    settings: Settings, demo_document: dict, tmp_path: Path
) -> None:
    path = write_registry(
        tmp_path,
        {
            "default": {"_all": ["ugc.gov.in"]},
            "engineering": {"market": ["josaa.nic.in"], "academics": ["aicte-india.org"]},
        },
    )
    scoped = dataclasses_replace(settings, domains_path=path, search_domains=())
    sent: dict[str, tuple[str, ...]] = {}

    class Recording(FakeClient):
        def complete_json(self, *, operation: str, search_domains=None, **kwargs: Any):
            sent[operation.split(":")[-1]] = search_domains
            return super().complete_json(operation=operation, **kwargs)

    generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        category=COURSE_CATEGORY,
        client=Recording(lambda op, _: chunk_payload(demo_document, op.split(":")[-1])),
        settings=scoped,
        discipline="Engineering",
    )

    assert sent["market"] == ("josaa.nic.in", "ugc.gov.in")
    assert sent["academics"] == ("aicte-india.org", "ugc.gov.in")
    assert sent["guidance"] == ("ugc.gov.in",)


def test_no_domains_anywhere_sends_no_search_filter(
    settings: Settings, demo_document: dict, tmp_path: Path
) -> None:
    scoped = dataclasses_replace(
        settings, domains_path=tmp_path / "absent.json", search_domains=()
    )
    sent: dict[str, tuple[str, ...]] = {}

    class Recording(FakeClient):
        def complete_json(self, *, operation: str, search_domains=None, **kwargs: Any):
            sent[operation.split(":")[-1]] = search_domains
            return super().complete_json(operation=operation, **kwargs)

    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        category=COURSE_CATEGORY,
        client=Recording(lambda op, _: chunk_payload(demo_document, op.split(":")[-1])),
        settings=scoped,
    )

    assert all(domains == () for domains in sent.values())
    assert result.status == "validated"


def test_unfiltered_course_is_not_punished_by_the_allowlist(
    root_schema: dict, demo_document: dict
) -> None:
    from coursegen.validate import RuleContext, validate_document

    off_domain = dict(demo_document)
    off_domain["verification"] = json.loads(json.dumps(demo_document["verification"]))
    off_domain["verification"]["sources"][0]["url"] = "https://some-college-blog.in/psychology"

    strict = RuleContext(currency="INR", allowed_domains=("ugc.gov.in",), search_filtered=True)
    assert "source_off_domain" in {
        f.code for f in validate_document(off_domain, root_schema, strict, scope="d").errors
    }

    unfiltered = RuleContext(currency="INR", allowed_domains=("ugc.gov.in",), search_filtered=False)
    report = validate_document(off_domain, root_schema, unfiltered, scope="d")
    assert report.passed, [f.to_dict() for f in report.errors]
    assert "sources_unfiltered" in {f.code for f in report.warnings}


def test_unfiltered_run_flags_nothing_but_warns_end_to_end(
    settings: Settings, demo_document: dict, tmp_path: Path
) -> None:
    scoped = dataclasses_replace(
        settings, domains_path=tmp_path / "absent.json", search_domains=()
    )

    def responder(operation: str, user_prompt: str) -> dict[str, Any]:
        payload = chunk_payload(demo_document, operation.split(":")[-1])
        if "verification" in payload:
            payload["verification"]["sources"][0]["url"] = "https://random-college-blog.in/x"
        return payload

    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        category=COURSE_CATEGORY,
        client=FakeClient(responder),
        settings=scoped,
    )

    assert result.status == "validated"
    assert result.publishable


def dataclasses_replace(settings: Settings, **changes: Any) -> Settings:
    import dataclasses

    return dataclasses.replace(settings, **changes)


def test_unsourced_chunks_are_surfaced(settings: Settings, demo_document: dict) -> None:
    class NoCitations(FakeClient):
        def complete_json(self, *, operation: str, search_domains=None, **kwargs: Any):
            response = super().complete_json(operation=operation, **kwargs)
            response.citations = []
            return response

    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        category=COURSE_CATEGORY,
        client=NoCitations(lambda op, _: chunk_payload(demo_document, op.split(":")[-1])),
        settings=settings,
    )
    payload = result.to_dict()
    assert result.status == "validated"
    assert sorted(payload["unsourced_chunks"]) == sorted(c["chunk"] for c in payload["chunks"])
    assert all(c["grounding"]["unsourced"] for c in payload["chunks"])


def test_grounding_records_the_domains_actually_sent(
    settings: Settings, demo_document: dict, tmp_path: Path
) -> None:
    path = write_registry(tmp_path, {"engineering": {"market": ["josaa.nic.in"]}})
    scoped = dataclasses_replace(settings, domains_path=path, search_domains=())
    result = generate_course(
        course_id=COURSE_ID,
        course_name=COURSE_NAME,
        category=COURSE_CATEGORY,
        client=FakeClient(lambda op, _: chunk_payload(demo_document, op.split(":")[-1])),
        settings=scoped,
        discipline="engineering",
    )
    chunks = {c["chunk"]: c for c in result.to_dict()["chunks"]}
    assert chunks["market"]["grounding"]["search_domains"] == ["josaa.nic.in"]
    assert chunks["guidance"]["grounding"]["search_domains"] == []
    assert chunks["market"]["grounding"]["unsourced"] is False
