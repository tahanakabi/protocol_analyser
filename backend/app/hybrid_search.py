"""Hybrid block search: BM25 keywords plus embedding similarity, fused by reciprocal rank.

Keyword search finds exact terms (``AESI``, ``5.1``, ``β-hCG``) that embeddings blur; semantic search finds
paragraphs that answer a question without sharing its words. Reciprocal rank fusion (RRF) combines the two
rankings without having to calibrate BM25 scores against cosine similarities: a block's fused score is
``sum(1 / (k + rank))`` over the rankings it appears in.

Both sides index the same text, ``Section: <section_path>`` followed by the block text.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

from app.schemas import SourceBlock

TOKEN_RE = re.compile(r"[a-z0-9\u00c0-\u024f\u0370-\u03ff]+(?:[.\-][a-z0-9\u00c0-\u024f\u0370-\u03ff]+)*")

STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how if in into is it its of on or per should "
    "that the their them there these they this to was were what when where which who will with would "
    "section study".split()
)

RRF_K = 60
DEFAULT_DEPTH = 50


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def block_search_text(block: SourceBlock) -> str:
    if block.section_path:
        return f"Section: {block.section_path}\n{block.text}"
    return block.text


class Bm25Index:
    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._tfs = [Counter(tokenize(t)) for t in texts]
        self._lengths = np.array([sum(tf.values()) for tf in self._tfs], dtype=np.float32)
        self._avg_length = float(self._lengths.mean()) if len(self._tfs) else 0.0
        df: Counter[str] = Counter()
        for tf in self._tfs:
            df.update(tf.keys())
        n = len(self._tfs)
        self._idf = {term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()}

    def scores(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self._tfs), dtype=np.float32)
        if not self._tfs or self._avg_length == 0:
            return scores
        norm = self.k1 * (1 - self.b + self.b * self._lengths / self._avg_length)
        for term in set(tokenize(query)):
            idf = self._idf.get(term)
            if idf is None:
                continue
            tf = np.array([doc.get(term, 0) for doc in self._tfs], dtype=np.float32)
            scores += idf * tf * (self.k1 + 1) / (tf + norm)
        return scores


@dataclass
class HybridHit:
    block: SourceBlock
    position: int
    score: float
    keyword_rank: int | None = None
    semantic_rank: int | None = None


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


class HybridIndex:
    """Blocks with a BM25 index and (optionally) a normalised embedding matrix."""

    def __init__(self, blocks: list[SourceBlock], vectors: np.ndarray | None) -> None:
        self.blocks = blocks
        self.bm25 = Bm25Index([block_search_text(b) for b in blocks])
        self._matrix: np.ndarray | None = None
        if vectors is not None and len(vectors) == len(blocks) and len(blocks):
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            self._matrix = (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)

    def __len__(self) -> int:
        return len(self.blocks)

    @property
    def has_vectors(self) -> bool:
        return self._matrix is not None

    def keyword_ranking(self, query: str, depth: int) -> list[int]:
        scores = self.bm25.scores(query)
        order = np.argsort(-scores, kind="stable")
        return [int(i) for i in order[:depth] if scores[i] > 0]

    def semantic_ranking(self, query_vector: list[float] | None, depth: int) -> list[int]:
        if self._matrix is None or query_vector is None:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        q /= np.linalg.norm(q) or 1.0
        order = np.argsort(-(self._matrix @ q), kind="stable")
        return [int(i) for i in order[:depth]]

    def search(
        self,
        keyword_query: str,
        query_vector: list[float] | None,
        k: int | None = None,
        depth: int = DEFAULT_DEPTH,
    ) -> list[HybridHit]:
        keyword = self.keyword_ranking(keyword_query, depth)
        semantic = self.semantic_ranking(query_vector, depth)
        fused = reciprocal_rank_fusion([keyword, semantic])
        keyword_rank = {item: rank for rank, item in enumerate(keyword, start=1)}
        semantic_rank = {item: rank for rank, item in enumerate(semantic, start=1)}
        ordered = sorted(fused, key=lambda i: (-fused[i], i))
        if k is not None:
            ordered = ordered[:k]
        return [
            HybridHit(
                block=self.blocks[i],
                position=i,
                score=fused[i],
                keyword_rank=keyword_rank.get(i),
                semantic_rank=semantic_rank.get(i),
            )
            for i in ordered
        ]
