"""Knowledge graph construction and querying with NetworkX."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import networkx as nx

from app.services.graph_rag.extractor import Entity, EntityExtractor, EntityType


@dataclass
class ChunkRecord:
    doc_id: str
    chunk_id: int
    text: str
    entities: list[Entity] = field(default_factory=list)


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks using sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for sentence in sentences:
        words = sentence.split()
        word_count = len(words)

        if current_len + word_count > chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk))
            overlap_words = (
                current_chunk[-chunk_overlap:]
                if len(current_chunk) > chunk_overlap
                else current_chunk[:]
            )
            current_chunk = overlap_words + words
            current_len = len(current_chunk)
        else:
            current_chunk.extend(words)
            current_len += word_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text[:4000]]


class KnowledgeGraph:
    """Builds and queries a knowledge graph from documents."""

    def __init__(self, extractor: EntityExtractor | None = None) -> None:
        self._graph = nx.DiGraph()
        self._extractor = extractor or EntityExtractor(use_llm=False)
        self._chunks: dict[str, ChunkRecord] = {}

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    @property
    def chunks(self) -> dict[str, ChunkRecord]:
        return self._chunks

    @property
    def entity_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def relationship_count(self) -> int:
        return self._graph.number_of_edges()

    def add_document(self, doc_id: str, text: str, chunks: list[str]) -> None:
        for i, chunk_body in enumerate(chunks):
            chunk_key = f"{doc_id}:{i}"
            entities = self._extractor.extract_entities(chunk_body, chunk_id=i)
            relationships = self._extractor.extract_relationships(
                chunk_body, entities, chunk_id=i
            )

            self._chunks[chunk_key] = ChunkRecord(
                doc_id=doc_id, chunk_id=i, text=chunk_body, entities=entities
            )

            for entity in entities:
                if self._graph.has_node(entity.id):
                    node_data = self._graph.nodes[entity.id]
                    node_data["mentions"] = node_data.get("mentions", 0) + entity.mentions
                    existing_chunks = node_data.get("source_chunks", [])
                    for sc in entity.source_chunks:
                        chunk_ref = f"{doc_id}:{sc}"
                        if chunk_ref not in existing_chunks:
                            existing_chunks.append(chunk_ref)
                    node_data["source_chunks"] = existing_chunks
                else:
                    self._graph.add_node(
                        entity.id,
                        name=entity.name,
                        entity_type=entity.entity_type.value,
                        mentions=entity.mentions,
                        source_chunks=[f"{doc_id}:{sc}" for sc in entity.source_chunks],
                    )

            for rel in relationships:
                if self._graph.has_edge(rel.source.id, rel.target.id):
                    edge_data = self._graph.edges[rel.source.id, rel.target.id]
                    edge_data["weight"] = edge_data.get("weight", 0) + rel.weight
                else:
                    self._graph.add_edge(
                        rel.source.id,
                        rel.target.id,
                        relation_type=rel.relation_type,
                        weight=rel.weight,
                        source_chunks=[f"{doc_id}:{sc}" for sc in rel.source_chunks],
                    )

    def get_entity_neighbors(self, entity_id: str, hops: int = 2) -> list[str]:
        if entity_id not in self._graph:
            return []

        visited: set[str] = set()
        frontier = {entity_id}

        for _ in range(hops):
            next_frontier: set[str] = set()
            for node in frontier:
                if node in visited:
                    continue
                visited.add(node)
                next_frontier.update(self._graph.successors(node))
                next_frontier.update(self._graph.predecessors(node))
            frontier = next_frontier - visited

        visited.update(frontier)
        visited.discard(entity_id)
        return list(visited)

    def get_relevant_chunks(self, query_entities: list[str]) -> list[ChunkRecord]:
        chunk_scores: dict[str, int] = {}

        for entity_id in query_entities:
            if entity_id not in self._graph:
                continue
            node_data = self._graph.nodes[entity_id]
            for chunk_key in node_data.get("source_chunks", []):
                chunk_scores[chunk_key] = chunk_scores.get(chunk_key, 0) + 1

        sorted_keys = sorted(chunk_scores, key=lambda k: chunk_scores[k], reverse=True)
        return [self._chunks[k] for k in sorted_keys if k in self._chunks]

    def find_entities_in_query(self, query: str) -> list[str]:
        query_lower = query.lower()
        matched: list[str] = []
        for node_id in self._graph.nodes:
            node_data = self._graph.nodes[node_id]
            name = node_data.get("name", "").lower()
            if name and name in query_lower:
                matched.append(node_id)
        return matched

    def to_dict(self) -> dict:
        return {
            "graph": nx.node_link_data(self._graph),
            "chunks": {
                key: {
                    "doc_id": chunk.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "entities": [
                        {
                            "name": e.name,
                            "entity_type": e.entity_type.value,
                            "mentions": e.mentions,
                            "source_chunks": e.source_chunks,
                        }
                        for e in chunk.entities
                    ],
                }
                for key, chunk in self._chunks.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> KnowledgeGraph:
        kg = cls()
        graph_data = data.get("graph", data)
        if "nodes" in graph_data:
            kg._graph = nx.node_link_graph(graph_data)
        chunks_data = data.get("chunks", {})
        for key, chunk_data in chunks_data.items():
            entities = [
                Entity(
                    name=e["name"],
                    entity_type=EntityType(e["entity_type"]),
                    mentions=e.get("mentions", 1),
                    source_chunks=e.get("source_chunks", []),
                )
                for e in chunk_data.get("entities", [])
            ]
            kg._chunks[key] = ChunkRecord(
                doc_id=chunk_data["doc_id"],
                chunk_id=chunk_data["chunk_id"],
                text=chunk_data["text"],
                entities=entities,
            )
        return kg

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> KnowledgeGraph:
        return cls.from_dict(json.loads(raw))
