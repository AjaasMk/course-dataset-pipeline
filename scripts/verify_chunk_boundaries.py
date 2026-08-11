"""Check stored LLM chunks against their source text.

Answers three things no aggregate count shows:
  1. is every chunk's text a verbatim slice of the source (Hard Constraint 2)?
  2. does any chunk begin or end mid-word?
  3. which documents produced nothing at all?

Run: PYTHONPATH=. python scripts/verify_chunk_boundaries.py
"""

import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

from src.extract.llm_chunker import document_text
from src.extract.readers import read_html, read_pdf

CHUNKS = "data/chunks_llm/*.json"


def source_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        text, _ = document_text(read_pdf(path))
        return text
    parts = []
    for section in read_html(path):
        if section.heading_title:
            parts.append(section.heading_title)
        parts.extend(section.paragraphs)
    return "\n\n".join(parts)


def main() -> int:
    conn = sqlite3.connect("data/manifest.db")
    paths = {d: p for d, p in conn.execute("select document_id, local_path from documents")}

    checked = verbatim_fail = start_mid = end_mid = 0
    empty_docs, unreadable = [], 0

    for file in sorted(glob.glob(CHUNKS)):
        document_id = os.path.basename(file)[:-5]
        chunks = json.loads(Path(file).read_text(encoding="utf-8"))
        if not chunks:
            empty_docs.append(document_id)
            continue
        raw_path = paths.get(document_id)
        if not raw_path or not os.path.exists(raw_path):
            continue
        try:
            text = source_text(Path(raw_path))
        except Exception:
            unreadable += 1
            continue

        for chunk in chunks:
            body = chunk.get("text") or ""
            if not body:
                continue
            checked += 1
            if body not in text:
                verbatim_fail += 1
                continue
            at = text.find(body)
            if at > 0 and not text[at - 1].isspace():
                start_mid += 1
            after = at + len(body)
            if after < len(text) and not text[after].isspace():
                end_mid += 1

    print(f"chunks checked against source : {checked}")
    if checked:
        print(f"  NOT verbatim in source      : {verbatim_fail}  ({100 * verbatim_fail / checked:.1f}%)")
        print(f"  begins mid-word             : {start_mid}  ({100 * start_mid / checked:.1f}%)")
        print(f"  ends mid-word               : {end_mid}  ({100 * end_mid / checked:.1f}%)")
    print(f"documents producing 0 chunks  : {len(empty_docs)}")
    for document_id in empty_docs[:10]:
        print(f"    {document_id}")
    if unreadable:
        print(f"documents unreadable          : {unreadable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
