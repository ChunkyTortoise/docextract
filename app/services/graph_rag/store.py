"""Persisted knowledge-graph store (JSON file, process-local singleton)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import settings
from app.services.graph_rag.extractor import EntityExtractor
from app.services.graph_rag.knowledge_graph import KnowledgeGraph, chunk_text
from app.services.graph_rag.retriever import GraphRetriever, RetrievedChunk

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_corpus: KnowledgeGraph | None = None


def _store_path() -> Path:
    return Path(settings.graph_store_path)


def _load_from_disk() -> KnowledgeGraph:
    path = _store_path()
    if path.exists():
        try:
            return KnowledgeGraph.from_json(path.read_text())
        except Exception as exc:
            logger.warning("Failed to load graph store %s: %s", path, exc)
    return KnowledgeGraph(extractor=EntityExtractor(use_llm=False))


def _save_to_disk(kg: KnowledgeGraph) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(kg.to_json())


def _ensure_corpus() -> KnowledgeGraph:
    global _corpus
    if _corpus is None:
        _corpus = _load_from_disk()
    return _corpus


def get_corpus() -> KnowledgeGraph:
    with _lock:
        return _ensure_corpus()


def reset_corpus(kg: KnowledgeGraph | None = None) -> None:
    """Reset in-process cache (for tests)."""
    global _corpus
    with _lock:
        _corpus = kg


def index_document(doc_id: str, text: str) -> None:
    if not text.strip():
        return
    chunks = chunk_text(text)
    with _lock:
        kg = _ensure_corpus()
        kg.add_document(doc_id, text, chunks)
        _save_to_disk(kg)


def search_graph(query: str, k: int = 5) -> list[RetrievedChunk]:
    with _lock:
        kg = _ensure_corpus()
        retriever = GraphRetriever(kg)
        retriever.build_index()
        return retriever.retrieve(query, k=k)
