"""Graph-aware multi-hop retrieval combining BM25 and graph traversal."""

from __future__ import annotations

from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from app.services.graph_rag.knowledge_graph import KnowledgeGraph


@dataclass
class RetrievedChunk:
    text: str
    chunk_id: int
    doc_id: str
    score: float
    source: str
    entity_ids: list[str] = field(default_factory=list)


class GraphRetriever:
    """Retriever that combines BM25 text search with knowledge graph traversal."""

    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        bm25_weight: float = 0.5,
        graph_weight: float = 0.5,
    ) -> None:
        self._kg = knowledge_graph
        self._bm25_weight = bm25_weight
        self._graph_weight = graph_weight
        self._bm25: BM25Okapi | None = None
        self._chunk_keys: list[str] = []

    def build_index(self) -> None:
        self._chunk_keys = list(self._kg.chunks.keys())
        if not self._chunk_keys:
            self._bm25 = None
            return
        corpus = [self._kg.chunks[k].text.lower().split() for k in self._chunk_keys]
        self._bm25 = BM25Okapi(corpus)

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        if not self._chunk_keys:
            return []

        bm25_scores = self._get_bm25_scores(query)
        graph_scores = self._get_graph_scores(query)

        all_keys = set(bm25_scores.keys()) | set(graph_scores.keys())
        combined: dict[str, float] = {}
        sources: dict[str, str] = {}

        for key in all_keys:
            b_score = bm25_scores.get(key, 0.0)
            g_score = graph_scores.get(key, 0.0)
            combined[key] = self._bm25_weight * b_score + self._graph_weight * g_score

            if b_score > 0 and g_score > 0:
                sources[key] = "both"
            elif g_score > 0:
                sources[key] = "graph"
            else:
                sources[key] = "bm25"

        ranked = sorted(combined.keys(), key=lambda k: combined[k], reverse=True)[:k]

        results: list[RetrievedChunk] = []
        for key in ranked:
            if key not in self._kg.chunks:
                continue
            chunk = self._kg.chunks[key]
            entity_ids = [e.id for e in chunk.entities]
            results.append(
                RetrievedChunk(
                    text=chunk.text,
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    score=combined[key],
                    source=sources.get(key, "bm25"),
                    entity_ids=entity_ids,
                )
            )

        return results

    def _get_bm25_scores(self, query: str) -> dict[str, float]:
        if self._bm25 is None:
            return {}

        tokenized_q = query.lower().split()
        raw_scores = self._bm25.get_scores(tokenized_q)
        max_score = max(raw_scores) if any(s > 0 for s in raw_scores) else 1.0

        scores: dict[str, float] = {}
        for i, key in enumerate(self._chunk_keys):
            if raw_scores[i] > 0:
                scores[key] = float(raw_scores[i] / (max_score + 1e-9))

        return scores

    def _get_graph_scores(self, query: str) -> dict[str, float]:
        query_entity_ids = self._kg.find_entities_in_query(query)
        if not query_entity_ids:
            return {}

        expanded: set[str] = set(query_entity_ids)
        for eid in query_entity_ids:
            neighbors = self._kg.get_entity_neighbors(eid, hops=2)
            expanded.update(neighbors)

        chunk_scores: dict[str, float] = {}
        for chunk_key, chunk_record in self._kg.chunks.items():
            chunk_entity_ids = {e.id for e in chunk_record.entities}
            overlap = len(expanded & chunk_entity_ids)
            if overlap > 0:
                chunk_scores[chunk_key] = overlap / len(expanded)

        if chunk_scores:
            max_val = max(chunk_scores.values())
            if max_val > 0:
                chunk_scores = {k: v / max_val for k, v in chunk_scores.items()}

        return chunk_scores
