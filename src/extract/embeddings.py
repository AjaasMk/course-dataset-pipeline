import sqlite3
import threading
from pathlib import Path
from typing import Optional

# Brute-force cosine over a course's segment chunks, not FAISS or Chroma. The
# candidate set is a few hundred vectors -- an ANN index would add a dependency
# and a staleness problem (an index that silently disagrees with the chunk files
# after a re-chunk) to save microseconds on a search that is already
# instantaneous. Revisit only if a single set grows past a few thousand.
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CACHE_DB = Path("data/embeddings.db")
DIMENSIONS = 384

_model = None
_lock = threading.Lock()


class EmbeddingsUnavailable(RuntimeError):
    """Raised instead of silently degrading to keyword-only retrieval.

    A vector stage that quietly disappears would make the evaluation harness
    report BM25 numbers under a hybrid label, which is the one failure mode that
    would make every later measurement untrustworthy.
    """


def _load_model():
    global _model
    with _lock:
        if _model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingsUnavailable(
                    "sentence-transformers is not installed; run "
                    "`pip install torch --index-url https://download.pytorch.org/whl/cpu "
                    "sentence-transformers`"
                ) from exc
            _model = SentenceTransformer(MODEL_NAME)
    return _model


def _connect() -> sqlite3.Connection:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        "create table if not exists embeddings ("
        " content_hash text primary key, model text not null, vector blob not null)"
    )
    return conn


def embed(texts: list[str], hashes: Optional[list[str]] = None):
    """Vectors for texts, cached by the chunk's existing content_hash.

    Caching on content_hash rather than chunk_id means re-running after a
    re-chunk only pays for spans whose text actually changed -- the sizing pass
    rewrote every chunk_id but left most text intact.
    """
    import numpy as np

    if not texts:
        return np.zeros((0, DIMENSIONS), dtype="float32")

    model = _load_model()
    if hashes is None:
        return _normalise(np.asarray(model.encode(texts, show_progress_bar=False), dtype="float32"))

    conn = _connect()
    try:
        cached: dict[str, bytes] = {}
        for i in range(0, len(hashes), 500):
            window = hashes[i : i + 500]
            placeholders = ",".join("?" * len(window))
            cached.update(
                conn.execute(
                    f"select content_hash, vector from embeddings "
                    f"where model = ? and content_hash in ({placeholders})",
                    [MODEL_NAME, *window],
                ).fetchall()
            )

        missing = [i for i, h in enumerate(hashes) if h not in cached]
        if missing:
            fresh = model.encode([texts[i] for i in missing], show_progress_bar=False)
            fresh = np.asarray(fresh, dtype="float32")
            conn.executemany(
                "insert or replace into embeddings (content_hash, model, vector) values (?, ?, ?)",
                [(hashes[i], MODEL_NAME, fresh[k].tobytes()) for k, i in enumerate(missing)],
            )
            conn.commit()
            for k, i in enumerate(missing):
                cached[hashes[i]] = fresh[k].tobytes()

        matrix = np.vstack([np.frombuffer(cached[h], dtype="float32") for h in hashes])
        return _normalise(matrix)
    finally:
        conn.close()


def _normalise(matrix):
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def cosine_rank(query: str, matrix, top_k: Optional[int] = None) -> list[tuple[int, float]]:
    """Indices ordered by cosine similarity, highest first.

    Vectors are unit-normalised on the way in, so the dot product is the cosine
    and no per-query division is needed.
    """
    import numpy as np

    if matrix.shape[0] == 0:
        return []
    vector = _normalise(
        np.asarray(_load_model().encode([query], show_progress_bar=False), dtype="float32")
    )[0]
    scores = matrix @ vector
    order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), i))
    ranked = [(i, float(scores[i])) for i in order]
    return ranked[:top_k] if top_k else ranked
