import math
import re
from typing import Iterable, Optional, Pattern

from rapidfuzz import fuzz, utils

# Titles from these sources carry a fixed scaffold around the one or two words
# that actually identify the subject. Left in, it inflates every candidate's
# similarity to every query and to every other candidate.
BOILERPLATE_PATTERNS: dict[str, Pattern] = {
    "AICTE": re.compile(
        r"\b(?:revised|aicte|model|curriculum|for|of|courses?|course|degree|programme|program|"
        r"at|in|the|ug|pg|under\s*graduate|post\s*graduate|level|vol\.?\s*[ivx]+|"
        r"\(?jan\s*\d{4}\)?|\d{4}|minor|diploma|bachelor|master)\b",
        re.IGNORECASE,
    ),
}

_NON_WORD = re.compile(r"[^a-z0-9]+")

# A taxonomy course name puts its specialisation marker in brackets --
# "Animation (Design/Art Track)", "Physical Education (Teaching Track)". Those
# words qualify the subject rather than identify it, so scoring them as
# distinctive costs the course its own subject's document: Animation
# (Design/Art Track) scored 0.27 against the real Animation diploma purely
# because "design", "art" and "track" are absent from that short title.
_QUERY_QUALIFIER = re.compile(r"\([^)]*\)")

# A candidate token carries no identifying weight below this length ("of",
# "and", "&"), so weighing it would only add noise.
_MIN_TOKEN_LEN = 3


def _tokens(text: str) -> set[str]:
    return {t for t in _NON_WORD.split((text or "").lower()) if len(t) >= _MIN_TOKEN_LEN}


class TokenWeights:
    """Inverse document frequency over one source's candidate titles.

    Which words identify a subject is a property of the corpus, not something
    to hand-list: in AICTE's index "engineering", "science" and "technology"
    appear everywhere and separate nothing, while "naval", "robotics" and
    "animation" each pick out one document. A word absent from the corpus
    entirely is maximally distinctive -- that is the case that matters, because
    every real false positive found in this project shares a COMMON word with
    the wrong document while the query's own distinctive word is missing:

        Mass Communication   -> Electronics and Communication Engineering
        Naval Architecture   -> Bachelor of Architecture
        Food Science & Tech  -> Computer Science and Engineering

    In each, "mass"/"naval"/"food" never appear in the candidate. In each real
    match that must survive -- Computer Engineering against Computer Science
    and Engineering, Robotics Engineering against Robotics & AI Engineering --
    the distinctive word is present.
    """

    def __init__(self, candidates: Iterable[str], boilerplate: Optional[Pattern] = None):
        stripped = [
            boilerplate.sub(" ", c) if boilerplate is not None else c for c in candidates
        ]
        self._total = max(len(stripped), 1)
        self._counts: dict[str, int] = {}
        for text in stripped:
            for token in _tokens(text):
                self._counts[token] = self._counts.get(token, 0) + 1

    def weight(self, token: str) -> float:
        # Smoothed rather than the textbook total/seen, so a token absent from
        # the corpus outranks one that appears exactly once. Unsmoothed,
        # log(1 + total/1) equals the ceiling, making "naval" -- which appears
        # in no AICTE title at all -- exactly as distinctive as "biotechnology",
        # which identifies one. The absent case is the one that decides false
        # positives, so it has to sit strictly higher.
        seen = self._counts.get(token, 0)
        return math.log(1 + self._total / (seen + 0.5))


def guarded_score(
    term: str,
    candidate: str,
    boilerplate: Optional[Pattern] = None,
    weights: Optional[TokenWeights] = None,
) -> float:
    """Similarity gated by whether the query's distinctive words are present.

    `token_set_ratio` deliberately ignores extra words in the candidate, which
    is right when a title merely adds qualifiers and wrong when those words
    change the subject. Measured against real data three times here: COA
    seminar posters beating regulations, JoSAA branch names matching unrelated
    branches, and "Mass Communication" scoring 0.84 against "Electronics and
    Communication Engineering" on the shared word alone.

    Two simpler guards were built and measured first, and both failed:
    penalising the CANDIDATE's unexplained tokens cut 7 real engineering
    bindings, because a course matching a broader document looks identical by
    that measure to a wrong match; weighting every query token equally cut the
    Animation bindings, because a long course name barely covers a short title.
    Weighting by IDF fixes both -- an unmatched common word ("engineering")
    costs almost nothing, an unmatched distinctive one ("naval") is decisive.

    Without `weights` this degrades to plain similarity, so adapters can adopt
    it one at a time.
    """
    stripped = boilerplate.sub(" ", candidate) if boilerplate is not None else candidate
    subject = _QUERY_QUALIFIER.sub(" ", term) or term
    candidate_tokens = _tokens(stripped)
    term_tokens = _tokens(subject) or _tokens(term)
    if not candidate_tokens or not term_tokens:
        return 0.0

    base = fuzz.token_set_ratio(subject, stripped, processor=utils.default_process) / 100
    if weights is None:
        return base

    total = sum(weights.weight(t) for t in term_tokens)
    if total == 0:
        return base
    matched = sum(weights.weight(t) for t in term_tokens & candidate_tokens)
    return base * (matched / total)
