import math
import re
from collections import Counter
from typing import Optional

# Okapi BM25. Written out rather than pulled from a package: it is forty lines,
# and every retrieval decision downstream depends on knowing exactly what the
# scoring does.
#
# Note on src/retrieve/matching.py::TokenWeights, which also computes IDF over a
# corpus and was the obvious thing to reuse: it deliberately weights an ABSENT
# token highest (log(1 + total/(seen + 0.5))), because its job is catching a
# query whose distinctive word is missing from a candidate title. BM25 needs the
# probabilistic form below, and needs term FREQUENCY, which TokenWeights discards
# by tokenising to a set. Different jobs, so the formula is not shared -- only
# the lesson that IDF must be measured from the corpus, never hand-listed.
K1 = 1.5
B = 0.75

_WORD = re.compile(r"[a-z][a-z0-9]*")
_MIN_TOKEN_LEN = 3


def tokenise(text: str) -> list[str]:
    return [t for t in _WORD.findall((text or "").lower()) if len(t) >= _MIN_TOKEN_LEN]


class BM25:
    def __init__(self, corpus: list[str], k1: float = K1, b: float = B):
        self.k1 = k1
        self.b = b
        self.docs = [tokenise(document) for document in corpus]
        self.n = len(self.docs)
        self.lengths = [len(d) for d in self.docs]
        self.avg_length = (sum(self.lengths) / self.n) if self.n else 0.0
        self.frequencies = [Counter(d) for d in self.docs]

        document_frequency: Counter = Counter()
        for document in self.docs:
            document_frequency.update(set(document))
        self.idf = {
            term: math.log(1 + (self.n - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }

    def score(self, query_terms: list[str], index: int) -> float:
        frequencies = self.frequencies[index]
        length = self.lengths[index]
        total = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            denominator = frequency + self.k1 * (
                1 - self.b + self.b * length / (self.avg_length or 1)
            )
            total += self.idf.get(term, 0.0) * frequency * (self.k1 + 1) / denominator
        return total

    def rank(self, query: str, top_k: Optional[int] = None) -> list[tuple[int, float]]:
        """Document indices ordered by score, highest first.

        Ties break on the original order so a run is reproducible; a retrieval
        stage that reorders equal-scoring chunks between runs would make the
        evaluation harness unable to tell a real change from noise.
        """
        terms = tokenise(query)
        scored = [(i, self.score(terms, i)) for i in range(self.n)]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top_k] if top_k else scored
