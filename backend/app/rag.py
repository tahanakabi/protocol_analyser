"""Question answering over one protocol: hybrid search on source blocks, then a cited LLM answer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from app.block_retrieval import amendment_pages
from app.config import settings
from app.hybrid_search import HybridHit
from app.openai_client import client, openai_embedder
from app.schemas import ChatAnswerLLM, ChatRequest, ChatResponse, ChatSource, SourceIndex
from app.vector_store import Embedder, registry

CHAT_SYSTEM = (
    "You answer questions about one clinical trial protocol using only the numbered source blocks given. "
    "Each block starts with its id in square brackets, e.g. [p12_b3]. "
    "Cite the blocks you used inline right after the statement they support, with the id in square "
    "brackets, e.g. 'Participants must be 18 or older [p40_b2].' "
    "List every cited id in cited_block_ids. "
    "If the blocks do not contain the answer, say that the protocol excerpts retrieved do not cover it; "
    "do not use outside knowledge. Keep answers concise; use short bullet lists for enumerations."
)

# Amendment summary-of-changes pages crowd out the current text unless the question is about changes.
AMENDMENT_QUESTION_RE = re.compile(r"amend|change|revis|version|history|previous|updated", re.IGNORECASE)

BLOCK_ID_RE = re.compile(r"\[(p\d+_b\d+)\]")
CITATION_RE = re.compile(r"\s*\[(p\d+_b\d+)\]")

Completer = Callable[[list[dict[str, str]]], ChatAnswerLLM]


def _openai_completer(messages: list[dict[str, str]]) -> ChatAnswerLLM:
    response = client().chat.completions.parse(
        model=settings.openai_model,
        messages=messages,
        response_format=ChatAnswerLLM,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Empty response from OpenAI")
    return parsed


def retrieval_query(request: ChatRequest) -> str:
    """Follow-ups like 'and for adolescents?' need the previous question to retrieve anything useful."""
    previous = [m.content for m in request.history if m.role == "user"][-1:]
    return "\n".join([*previous, request.question])


def format_context(hits: list[HybridHit]) -> str:
    parts = []
    for hit in hits:
        block = hit.block
        section = f", section {block.section_path}" if block.section_path else ""
        parts.append(f"[{block.id}] (page {block.page}{section})\n{block.text}")
    return "\n\n".join(parts)


def build_messages(request: ChatRequest, hits: list[HybridHit]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": CHAT_SYSTEM}]
    history = request.history[-settings.chat_history_turns :]
    messages.extend({"role": m.role, "content": m.content} for m in history)
    messages.append(
        {
            "role": "user",
            "content": f"Source blocks:\n\n{format_context(hits)}\n\nQuestion: {request.question}",
        }
    )
    return messages


def answer_question(
    document_id: str,
    source_index: SourceIndex,
    request: ChatRequest,
    cache_path: Path | None,
    embed: Embedder | None = None,
    complete: Completer | None = None,
) -> ChatResponse:
    embed = embed or openai_embedder()
    complete = complete or _openai_completer
    index = registry.get(document_id, source_index, embed, settings.openai_embedding_model, cache_path)
    query = retrieval_query(request)
    query_vector = embed([query])[0] if index.has_vectors else None
    skip = set() if AMENDMENT_QUESTION_RE.search(request.question) else amendment_pages(index.blocks)
    hits = [h for h in index.search(query, query_vector) if h.block.page not in skip][: settings.chat_top_k]

    raw = complete(build_messages(request, hits))
    retrieved = {hit.block.id for hit in hits}
    cited = {i for i in [*raw.cited_block_ids, *BLOCK_ID_RE.findall(raw.answer)] if i in retrieved}
    answer = CITATION_RE.sub(lambda m: m.group(0) if m.group(1) in retrieved else "", raw.answer)

    return ChatResponse(
        answer=answer.strip(),
        retrieval="hybrid" if query_vector is not None else "keyword",
        sources=[
            ChatSource(
                block_id=hit.block.id,
                page=hit.block.page,
                bbox=hit.block.bbox,
                section_path=hit.block.section_path,
                text=hit.block.text,
                score=round(hit.score, 4),
                keyword_rank=hit.keyword_rank,
                semantic_rank=hit.semantic_rank,
                cited=hit.block.id in cited,
            )
            for hit in hits
        ],
    )
