"""Measure how much of a DeepSeek response the reasoning block consumes.

The compatibility endpoint always emits a `thinking` block before the answer
and it spends output tokens, so a window/max_tokens pair that works for one
document size can silently return no text at all for a larger one. This finds
a pairing that leaves room for the answer.

Run: PYTHONPATH=. python scripts/probe_chunk_window.py
"""

import json
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from src.extract.llm_chunker import SEGMENT_NAMES, SYSTEM_PROMPT, document_text
from src.extract.llm_clients import client_for, model_for
from src.extract.readers import read_pdf

TRIALS = ((8000, 16000), (8000, 32000))
# Reasoning is unbounded on this endpoint: measured 48k-62k characters of
# thinking regardless of whether the window was 4k or 12k characters, always
# exhausting max_tokens before any answer. So the useful question is not window
# size but whether thinking can be switched off at all.
THINKING_MODES = (None, {"type": "disabled"})


def main() -> None:
    load_dotenv()

    conn = sqlite3.connect("data/manifest.db")
    docs = json.load(open("data/pilot25_documents.json"))
    rows = {d: (s, p) for d, s, p in conn.execute("select document_id,source_id,local_path from documents")}
    doc = next(d for d in docs if rows[d][0] == "AICTE" and rows[d][1].endswith(".pdf"))

    text, _ = document_text(read_pdf(Path(rows[doc][1])))
    print(f"document: {Path(rows[doc][1]).name[:60]}")
    print(f"chars: {len(text):,}")
    print()

    client = client_for("deepseek")
    model = model_for("deepseek", "fast")
    system = SYSTEM_PROMPT.format(segments=", ".join('"%s"' % s for s in SEGMENT_NAMES))

    for window_chars, max_tokens in TRIALS:
      for thinking in THINKING_MODES:
        prompt = (
            f"document_id: {doc}\ncharacter_offset_of_first_character: 0\n"
            f"--- DOCUMENT TEXT ---\n{text[:window_chars]}"
        )
        kwargs = {"thinking": thinking} if thinking else {}
        label = "thinking=off" if thinking else "thinking=on "
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system}],
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
        except Exception as exc:
            print(f"{label} window={window_chars:>6} max={max_tokens} -> {type(exc).__name__}: {str(exc)[:110]}")
            continue

        think_chars = sum(len(b.thinking or "") for b in response.content if b.type == "thinking")
        body = next((b.text for b in response.content if b.type == "text"), None)
        print(
            f"{label} window={window_chars:>6} max={max_tokens} "
            f"stop={response.stop_reason:<12} out={response.usage.output_tokens:>6} "
            f"think_chars={think_chars:>6} text={'yes' if body else 'NONE'}"
        )
        if body:
            print(f"    answer starts: {body[:120]!r}")


if __name__ == "__main__":
    main()
