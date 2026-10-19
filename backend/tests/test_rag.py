from app.hybrid_search import block_search_text
from app.rag import answer_question, retrieval_query
from app.schemas import ChatAnswerLLM, ChatMessage, ChatRequest, SourceBlock, SourceIndex
from app.vector_store import IndexRegistry, build_index

VOCAB = ["inclusion", "exclusion", "pregnant", "adult", "dose", "visit"]


def fake_embed(texts: list[str]) -> list[list[float]]:
    return [[float(text.lower().count(word)) for word in VOCAB] for text in texts]


def _index() -> SourceIndex:
    blocks = [
        SourceBlock(id="p40_b0", page=40, bbox=[0, 0, 1, 1], text="Adult, 18 years or older.", section_path="5.1 Inclusion Criteria"),
        SourceBlock(id="p41_b0", page=41, bbox=[0, 0, 1, 1], text="Pregnant or breastfeeding women.", section_path="5.2 Exclusion Criteria"),
        SourceBlock(id="p50_b0", page=50, bbox=[0, 0, 1, 1], text="Two doses 4 weeks apart.", section_path="6.1 Dose"),
    ]
    return SourceIndex(document_sha256="x", blocks=blocks, index_version=4)


def test_section_path_is_part_of_the_indexed_text():
    block = _index().blocks[1]

    assert block_search_text(block) == "Section: 5.2 Exclusion Criteria\nPregnant or breastfeeding women."


def test_hybrid_search_ranks_by_section_and_text(tmp_path):
    index = build_index(_index(), fake_embed, "fake", tmp_path / "embeddings.npz")

    hits = index.search("exclusion criteria", fake_embed(["exclusion criteria"])[0], k=2)

    assert hits[0].block.id == "p41_b0"
    assert hits[0].keyword_rank == 1 and hits[0].semantic_rank == 1


def test_embeddings_are_cached_on_disk(tmp_path):
    calls = []

    def counting_embed(texts):
        calls.append(len(texts))
        return fake_embed(texts)

    cache = tmp_path / "embeddings.npz"
    build_index(_index(), counting_embed, "fake", cache)
    build_index(_index(), counting_embed, "fake", cache)
    changed = _index().model_copy(update={"blocks": _index().blocks[:2]})
    build_index(changed, counting_embed, "fake", cache)

    assert calls == [3, 2]


def test_failed_embedding_falls_back_to_keywords_and_retries(tmp_path):
    def broken(texts):
        raise RuntimeError("network down")

    registry = IndexRegistry()
    index = registry.get("doc", _index(), broken, "fake", None)
    assert not index.has_vectors
    assert index.search("pregnant", None, k=1)[0].block.id == "p41_b0"

    assert registry.get("doc", _index(), fake_embed, "fake", None).has_vectors


def test_amendment_pages_only_retrieved_for_change_questions(tmp_path, monkeypatch):
    amendment = SourceBlock(
        id="p120_b0", page=120, bbox=[0, 0, 1, 1],
        text="Description of Change\nBrief Rationale\nExcluded pregnant women", section_path="5.2 Exclusion Criteria",
    )
    source = _index().model_copy(update={"blocks": [*_index().blocks, amendment]})

    def ask(question):
        monkeypatch.setattr("app.rag.registry", IndexRegistry())
        response = answer_question(
            "doc", source, ChatRequest(question=question), None,
            embed=fake_embed, complete=lambda m: ChatAnswerLLM(answer="ok"),
        )
        return {s.block_id for s in response.sources}

    assert "p120_b0" not in ask("Are pregnant women excluded?")
    assert "p120_b0" in ask("How did the amendment change the pregnant exclusion?")


def test_follow_up_question_includes_previous_question():
    request = ChatRequest(
        question="And the exclusions?",
        history=[ChatMessage(role="user", content="Who can enroll?"), ChatMessage(role="assistant", content="Adults.")],
    )

    assert retrieval_query(request) == "Who can enroll?\nAnd the exclusions?"


def test_answer_keeps_only_citations_from_retrieved_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rag.registry", IndexRegistry())
    seen = []

    def fake_complete(messages):
        seen.append(messages)
        return ChatAnswerLLM(
            answer="Pregnant women are excluded [p41_b0]. Made up [p99_b9].",
            cited_block_ids=["p41_b0", "p99_b9"],
        )

    response = answer_question(
        "doc",
        _index(),
        ChatRequest(question="Are pregnant women excluded?"),
        tmp_path / "embeddings.npz",
        embed=fake_embed,
        complete=fake_complete,
    )

    assert "[p41_b0] (page 41, section 5.2 Exclusion Criteria)" in seen[0][-1]["content"]
    assert response.answer == "Pregnant women are excluded [p41_b0]. Made up."
    assert response.retrieval == "hybrid"
    assert [s.block_id for s in response.sources if s.cited] == ["p41_b0"]
    assert response.sources[0].block_id == "p41_b0"
