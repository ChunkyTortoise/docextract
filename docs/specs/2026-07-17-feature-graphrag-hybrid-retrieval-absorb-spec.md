# Spec: GraphRAG hybrid retrieval absorb (graphrag-demo → docextract)

**Date:** 2026-07-17  
**Status:** Implement  
**Lane:** AI Engineer — RAG / evals / DocAI (B1)

## Goal

Add an **opt-in** graph-aware retrieval mode to DocExtract by absorbing core retrieval logic from `graphrag-demo` — not a repo merge. Default path remains pgvector `mode=vector`.

## Non-goals

- New vector DB or Neo4j
- spaCy as hard dependency (regex NER is default; spaCy optional later)
- Live traffic A/B or funded cost/latency benchmark
- Porting Streamlit comparison UI from graphrag-demo

## Interface contract

| Surface | Behavior |
|---------|----------|
| Settings | `graph_retrieval_enabled: bool = False` (`GRAPH_RETRIEVAL_ENABLED`) |
| Store path | `graph_store_path: str = "data/knowledge_graph.json"` |
| `GET /records/search?mode=graph` | Graph+BM25 weighted retrieval over persisted corpus; 400 if flag off |
| `GET /records/search?mode=hybrid` | Unchanged (vector+BM25 RRF) when flag off; when flag on, **three-way RRF** (vector + BM25 + graph ranks, k=60) |
| `RagTools.search_graph` | Agent tool; no-op empty list when flag off |
| Ingest | After embedding persist in `worker/tasks.py`, if flag on: extract entities, `KnowledgeGraph.add_document(record_id, text, [chunks])`, persist JSON |

## Data model

- In-memory NetworkX DiGraph + chunk map, serialized via `KnowledgeGraph.to_dict()` / `from_dict()` to `graph_store_path`.
- Document key = `ExtractedRecord.id` (or document id already used in search results).
- Chunking: simple ~500-char windows with overlap 50 (port `chunk_text` utility).

## Modules to add

```
app/services/graph_rag/
  __init__.py
  extractor.py      # EntityExtractor (regex default, LLM off in tests)
  knowledge_graph.py
  retriever.py      # GraphRetriever (BM25 + graph weighted blend)
  store.py          # load/save JSON; get_or_create singleton for process
```

Deps: add `networkx>=3.3` to `requirements_full.txt` / `requirements_ci.txt` (rank-bm25 already present).

## Eval

- Unit tests: entity extract, multi-hop neighbors, RRF three-way rank merge, flag-off leaves default search unchanged.
- Honest README: one engineering bullet; no measured GraphRAG lift until ledger `status: measured` row exists.

## Rollout

1. Land modules + flag + tests (this PR).
2. Enable in DEMO_MODE stub JSON with `retrieval_mode: "graph"`.
3. Optional follow-up: Streamlit mode selector when flag on.
