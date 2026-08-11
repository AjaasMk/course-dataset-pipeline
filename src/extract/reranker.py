import threading
from typing import Optional

# A cross-encoder, not a second bi-encoder: it reads the query and the chunk
# together and scores the pair, which is what makes it worth running after
# BM25 and vector search have already narrowed the field. It is far too slow to
# run over a whole document, which is exactly why it sits at the top-30 stage.
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_model = None
_lock = threading.Lock()


class RerankerUnavailable(RuntimeError):
    """Raised rather than passing the input through unchanged.

    Silently skipping the rerank would leave the fusion order in place while
    the report still said "reranked", and every metric after it would be
    measuring something other than what it claimed.
    """


def _load_model():
    global _model
    with _lock:
        if _model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RerankerUnavailable(
                    "sentence-transformers is not installed; run "
                    "`pip install torch --index-url https://download.pytorch.org/whl/cpu "
                    "sentence-transformers`"
                ) from exc
            _model = CrossEncoder(MODEL_NAME)
    return _model


def rerank(query: str, texts: list[str], top_k: Optional[int] = None) -> list[tuple[int, float]]:
    if not texts:
        return []
    scores = _load_model().predict([(query, text) for text in texts])
    order = sorted(range(len(texts)), key=lambda i: (-float(scores[i]), i))
    ranked = [(i, float(scores[i])) for i in order]
    return ranked[:top_k] if top_k else ranked


def reciprocal_rank_fusion(
    rankings: list[list[int]], top_k: Optional[int] = None, k: int = 60
) -> list[int]:
    """Combine several rankings without needing their scores to be comparable.

    BM25 returns unbounded term-saturation sums and cosine returns [-1, 1];
    normalising either into the other's space would invent a calibration that
    does not exist. RRF only uses positions, so it needs no such assumption --
    the constant k damps the influence of the very top ranks so one confident
    list cannot dominate a whole fusion.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, index in enumerate(ranking):
            scores[index] = scores.get(index, 0.0) + 1.0 / (k + position + 1)
    order = sorted(scores, key=lambda i: (-scores[i], i))
    return order[:top_k] if top_k else order
