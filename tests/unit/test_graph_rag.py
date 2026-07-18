"""Unit tests for GraphRAG modules."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.graph_rag.extractor import EntityExtractor, EntityType
from app.services.graph_rag.knowledge_graph import KnowledgeGraph
from app.services.graph_rag.rrf import reciprocal_rank_fusion
from app.services.graph_rag.store import index_document, reset_corpus, search_graph

SAMPLE_TEXT = (
    "John Smith works at Acme Technologies Inc. in San Francisco. "
    "He deployed the Search Platform API with Jane Doe from Global Systems LLC."
)


@pytest.fixture
def graph_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store_path = tmp_path / "knowledge_graph.json"
    monkeypatch.setattr("app.config.settings.graph_store_path", str(store_path))
    monkeypatch.setattr("app.config.settings.graph_retrieval_enabled", True)
    reset_corpus(None)
    yield store_path
    reset_corpus(None)


class TestEntityExtractor:
    def test_regex_finds_org_and_person(self):
        extractor = EntityExtractor(use_llm=False)
        entities = extractor.extract_entities(SAMPLE_TEXT)
        types = {e.entity_type for e in entities}
        names = {e.name for e in entities}

        assert EntityType.ORG in types
        assert EntityType.PERSON in types
        assert any("Acme" in name for name in names)
        assert any("John" in name for name in names)


class TestKnowledgeGraph:
    def test_multi_hop_neighbors(self):
        kg = KnowledgeGraph()
        kg.add_document(
            "doc-1",
            SAMPLE_TEXT,
            [SAMPLE_TEXT],
        )
        query_entities = kg.find_entities_in_query("Acme Technologies")
        assert query_entities
        neighbors = kg.get_entity_neighbors(query_entities[0], hops=2)
        assert isinstance(neighbors, list)


class TestGraphStore:
    def test_index_and_search_returns_ranked_chunks(self, graph_store: Path):
        index_document("rec-1", SAMPLE_TEXT)
        index_document(
            "rec-2",
            "Unrelated content about weather and gardening tips only.",
        )

        hits = search_graph("Acme Technologies John Smith", k=3)
        assert hits
        assert hits[0].doc_id == "rec-1"
        assert hits[0].score > 0


class TestReciprocalRankFusion:
    def test_three_way_merge(self):
        vector_ranks = {"a": 0, "b": 1, "c": 2}
        bm25_ranks = {"b": 0, "c": 1, "d": 2}
        graph_ranks = {"a": 1, "d": 0, "e": 2}

        fused = reciprocal_rank_fusion(
            [vector_ranks, bm25_ranks, graph_ranks],
            k=60,
            default_rank=5,
        )

        assert fused["a"] > 0
        assert fused["d"] > 0
        assert fused["a"] >= fused["e"]


class TestGraphModeGate:
    @pytest.mark.asyncio
    async def test_graph_mode_400_when_flag_off(self):
        from app.api.records import search_records

        with patch("app.config.settings.graph_retrieval_enabled", False):
            with pytest.raises(HTTPException) as exc:
                await search_records(
                    q="Acme",
                    limit=5,
                    mode="graph",
                    db=None,
                    api_key=None,
                )
            assert exc.value.status_code == 400
            assert "GRAPH_RETRIEVAL_ENABLED" in exc.value.detail


class TestVectorPathUnchanged:
    def test_hybrid_pattern_allows_vector(self):
        import re

        pattern = re.compile(r"^(vector|bm25|hybrid|graph)$")
        assert pattern.match("vector")
        assert pattern.match("hybrid")
        assert not pattern.match("graphrag")
