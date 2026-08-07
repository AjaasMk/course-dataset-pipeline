import argparse
import json
import sys
import time
from pathlib import Path

from urllib.parse import urlparse

import requests

from src.retrieve.probe import BROWSER_HEADERS, ProbeResult, ProbeVerdict, classify
from src.retrieve.registry import load_registry
from src.retrieve.tls import verify_arg

REQUEST_TIMEOUT = 25
DELAY_SECONDS = 1.5


def probe(source_id: str, url: str) -> ProbeResult:
    note_prefix = ""
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.SSLError:
        host = urlparse(url).hostname or ""
        verify = verify_arg(host)
        if verify is True:
            return ProbeResult(
                source_id=source_id,
                url=url,
                verdict=ProbeVerdict.ERROR,
                note="TLS chain incomplete and no AIA issuer available",
            )
        try:
            response = requests.get(
                url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT, verify=verify
            )
        except requests.RequestException as exc:
            return ProbeResult(
                source_id=source_id,
                url=url,
                verdict=ProbeVerdict.ERROR,
                note=f"after CA repair: {type(exc).__name__}",
            )
        note_prefix = "CA chain repaired; "
    except requests.RequestException as exc:
        return ProbeResult(
            source_id=source_id, url=url, verdict=ProbeVerdict.ERROR, note=f"{type(exc).__name__}"
        )

    result = classify(response.status_code, response.text)
    result.source_id = source_id
    result.url = url
    result.note = note_prefix + result.note
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="source_ids to probe; default is all")
    parser.add_argument("--out", type=Path, default=Path("data/source_probe_report.json"))
    args = parser.parse_args()

    registry = load_registry()
    targets = args.only or list(registry.sources)

    results: list[ProbeResult] = []
    for n, source_id in enumerate(targets):
        source = registry.sources.get(source_id)
        if source is None:
            print(f"  ?? {source_id}: not in registry", file=sys.stderr)
            continue

        url = source.listing_page or source.official_url
        result = probe(source_id, url)
        results.append(result)
        print(f"  {result.verdict.value:16} {source_id:24} {result.note}")

        if n < len(targets) - 1:
            time.sleep(DELAY_SECONDS)

    summary = {v.value: sum(1 for r in results if r.verdict is v) for v in ProbeVerdict}
    payload = {
        "summary": summary,
        "reachable": sorted(
            r.source_id for r in results if r.verdict is ProbeVerdict.SERVER_RENDERED
        ),
        "results": [r.model_dump() for r in results],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n{json.dumps(summary)}")
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
