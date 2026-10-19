"""In-memory search index over a document's source blocks.

Each block is embedded together with its section path, so a question about "exclusion criteria" also
matches paragraphs whose own text never says so. Vectors live in a NumPy matrix next to a BM25 index
(see ``hybrid_search``); for the few hundred blocks of one protocol a full scan is instant. Embeddings are
cached in ``embeddings.npz`` next to the source index so a restart does not pay for them again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from app.hybrid_search import HybridIndex, block_search_text
from app.schemas import SourceIndex

logger = logging.getLogger(__name__)

EMBED_BATCH = 128

Embedder = Callable[[list[str]], list[list[float]]]


def index_fingerprint(source_index: SourceIndex, model: str) -> str:
    digest = hashlib.sha256(model.encode())
    for block in source_index.blocks:
        digest.update(block.id.encode())
        digest.update(block_search_text(block).encode())
    return digest.hexdigest()


def _embed_all(texts: list[str], embed: Embedder) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(embed(texts[start : start + EMBED_BATCH]))
    return np.asarray(vectors, dtype=np.float32)


def _load_cached(path: Path, fingerprint: str) -> np.ndarray | None:
    if not path.exists():
        return None
    try:
        with np.load(path) as data:
            if json.loads(str(data["meta"]))["fingerprint"] != fingerprint:
                return None
            return data["vectors"]
    except (OSError, KeyError, ValueError):
        return None


def load_or_embed(
    source_index: SourceIndex,
    embed: Embedder | None,
    model: str,
    cache_path: Path | None,
) -> np.ndarray | None:
    """Block vectors from the cache, or freshly embedded; ``None`` means keyword search only."""
    if not source_index.blocks:
        return None
    fingerprint = index_fingerprint(source_index, model)
    vectors = _load_cached(cache_path, fingerprint) if cache_path else None
    if vectors is not None or embed is None:
        return vectors
    try:
        vectors = _embed_all([block_search_text(b) for b in source_index.blocks], embed)
    except Exception:
        logger.warning("Embedding failed; falling back to keyword-only search", exc_info=True)
        return None
    if cache_path:
        meta = json.dumps({"fingerprint": fingerprint, "model": model})
        np.savez(cache_path, vectors=vectors, meta=np.array(meta))
    return vectors


def build_index(
    source_index: SourceIndex,
    embed: Embedder | None,
    model: str,
    cache_path: Path | None,
) -> HybridIndex:
    return HybridIndex(source_index.blocks, load_or_embed(source_index, embed, model, cache_path))


class IndexRegistry:
    """One index per document, rebuilt when the document's blocks change."""

    def __init__(self) -> None:
        self._indexes: dict[str, tuple[str, HybridIndex]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, document_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(document_id, threading.Lock())

    def get(
        self,
        document_id: str,
        source_index: SourceIndex,
        embed: Embedder | None,
        model: str,
        cache_path: Path | None,
    ) -> HybridIndex:
        fingerprint = index_fingerprint(source_index, model)
        with self._lock(document_id):
            cached = self._indexes.get(document_id)
            # A keyword-only index (embedding failed earlier) is retried once an embedder is available.
            if cached and cached[0] == fingerprint and (cached[1].has_vectors or embed is None):
                return cached[1]
            index = build_index(source_index, embed, model, cache_path)
            self._indexes[document_id] = (fingerprint, index)
            return index


registry = IndexRegistry()
