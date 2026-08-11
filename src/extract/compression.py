import re

from src.extract.bm25 import tokenise

# Strictly extractive. Sentences are kept or dropped whole and never rewritten,
# so a retained span is still a byte-identical slice of the stored document and
# quoted evidence taken from it still validates (Hard Constraint 2). An LLM
# compressor would read better and break exactly that.
#
# The keep-list is the caller's: subject names, subject codes, credits, units,
# topics, learning outcomes, syllabus detail. Anything scoring nothing against
# the query vocabulary is preamble, acknowledgement or reference matter.
MIN_KEEP_RATIO = 0.25
NEIGHBOUR_RADIUS = 1

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?|\n+")
_STRUCTURAL = re.compile(
    r"\b(?:credits?|semester|unit|units|code|marks|hours|l\s*t\s*p|elective|core|lab|"
    r"practical|project|internship|module|outcome)\b|\d",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for m in _SENTENCE.finditer(text) if m.group().strip()]
    return spans or [(0, len(text))]


def compress(text: str, query: str, min_keep_ratio: float = MIN_KEEP_RATIO) -> str:
    """Drop the sentences in one chunk that carry no query-relevant content.

    Returns a string built only from spans of the input, in their original
    order. A chunk whose sentences all score zero is returned unchanged rather
    than emptied: no signal is a reason to keep looking, not a reason to throw
    the evidence away.
    """
    if not text.strip():
        return text

    terms = set(tokenise(query))
    spans = _sentences(text)
    scores = []
    for start, end in spans:
        body = text[start:end]
        overlap = len(terms & set(tokenise(body)))
        # A syllabus row is mostly codes and numbers, so it can carry almost no
        # query WORDS while being exactly what we came for. Structural markers
        # rescue those rows from being scored as noise.
        scores.append(overlap + (1 if _STRUCTURAL.search(body) else 0))

    if not any(scores):
        return text

    keep = {i for i, score in enumerate(scores) if score}
    for index in sorted(keep):
        for offset in range(1, NEIGHBOUR_RADIUS + 1):
            keep.add(max(0, index - offset))
            keep.add(min(len(spans) - 1, index + offset))

    kept = "".join(text[spans[i][0] : spans[i][1]] for i in sorted(keep))
    # Compression that barely compresses is not worth the risk of having cut
    # something load-bearing.
    if len(kept) < len(text) * min_keep_ratio:
        return text
    return kept
