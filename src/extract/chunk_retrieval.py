import hashlib
from dataclasses import dataclass, field
from typing import Optional

from src.extract.bm25 import BM25
from src.extract.compression import compress
from src.extract.models import Chunk
from src.extract.segment_queries import query_for

# The funnel, as specified. Each cut is a named constant so the evaluation
# harness can move one and re-measure rather than the numbers being buried in
# the code.
#
# Measured 2026-08-11 on 20 real Curriculum extractions (136 gold chunks):
# recall@5 is 0.475 for BM25, 0.495 fused, 0.466 reranked -- the reranker does
# not rescue Curriculum, whose evidence is genuinely diffuse (recall keeps
# climbing to 0.892 at rank 50). TOP_K stays 5 by explicit instruction; the
# uncited remainder is expected to be filled by field-level generation, not by
# widening this.
FUSION_TOP_K = 30
TOP_K = 5

# Curriculum is the exception, and it is measured rather than assumed. Its
# evidence is genuinely diffuse -- 136 gold chunks across 20 real extractions,
# recall still climbing at rank 50 -- because core_subjects is an enumeration
# (every subject across 8 semesters), not a single-passage answer that a
# reranker can put in one slot. At 5 the fused ranking recalls 0.495; at 20 it
# recalls 0.705. With ~700-token chunks that is ~14k tokens, still a 92% cut
# against the 165k a whole-segment call used to send.
TOP_K_BY_SEGMENT = {"Curriculum": 20}


@dataclass
class RetrievalResult:
    """The chosen chunks, and every stage's survivors alongside them.

    Stages are kept rather than discarded so a bad extraction can be explained
    offline -- which stage dropped the evidence is answerable without spending
    an API call to reproduce it.
    """

    chunks: list[Chunk]
    stages: dict[str, list[int]] = field(default_factory=dict)
    chars_before: int = 0
    chars_after: int = 0

    @property
    def reduction(self) -> float:
        if not self.chars_before:
            return 0.0
        return 1 - (self.chars_after / self.chars_before)


def retrieve(
    chunks: list[Chunk],
    segment: str,
    top_k: Optional[int] = None,
    fusion_top_k: int = FUSION_TOP_K,
    compress_context: bool = True,
) -> RetrievalResult:
    if not chunks:
        return RetrievalResult(chunks=[])

    if top_k is None:
        top_k = TOP_K_BY_SEGMENT.get(segment, TOP_K)
    query = query_for(segment)
    texts = [c.text for c in chunks]
    before = sum(len(t) for t in texts)

    if len(chunks) <= top_k:
        # Nothing to rank. Loading two transformer models to reorder four
        # chunks that are all going to be sent anyway is pure overhead.
        return _finalise(chunks, list(range(len(chunks))), {}, query, before, compress_context)

    from src.extract.embeddings import cosine_rank, embed
    from src.extract.reranker import reciprocal_rank_fusion, rerank

    hashes = [hashlib.sha256(t.encode("utf-8")).hexdigest()[:16] for t in texts]
    bm25 = [i for i, _ in BM25(texts).rank(query)]
    vector = [i for i, _ in cosine_rank(query, embed(texts, hashes))]
    fused = reciprocal_rank_fusion([bm25, vector], top_k=fusion_top_k)
    reranked = [fused[i] for i, _ in rerank(query, [texts[i] for i in fused], top_k=top_k)]

    stages = {"bm25": bm25, "vector": vector, "fusion": fused, "rerank": reranked}
    return _finalise(chunks, reranked, stages, query, before, compress_context)


def _finalise(
    chunks: list[Chunk],
    selected: list[int],
    stages: dict[str, list[int]],
    query: str,
    chars_before: int,
    compress_context: bool,
) -> RetrievalResult:
    # Restored to document order before returning: the reranker's order is a
    # relevance judgement, but a curriculum reads in sequence and handing the
    # model shuffled semesters would invent a discontinuity that is not in the
    # source.
    ordered = sorted(selected, key=lambda i: chunks[i].chunk_id)
    out: list[Chunk] = []
    for index in ordered:
        chunk = chunks[index]
        body = compress(chunk.text, query) if compress_context else chunk.text
        out.append(chunk.model_copy(update={"text": body}))
    return RetrievalResult(
        chunks=out,
        stages=stages,
        chars_before=chars_before,
        chars_after=sum(len(c.text) for c in out),
    )
