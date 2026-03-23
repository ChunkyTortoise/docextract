# ADR-0002: pgvector over Pinecone/Weaviate for Vector Storage

**Status**: Accepted
**Date**: 2026-01

## Context

Document embeddings must be stored and queried for semantic search. DocExtract already depends on PostgreSQL for relational data (jobs, records, API keys, audit logs).

## Decision

Store document embeddings in PostgreSQL via the pgvector extension rather than a dedicated vector database.

## Consequences

**Why:** Adding pgvector keeps the system at one storage dependency instead of two. Vector records stay in the same ACID transaction as their parent `extracted_records` row — no risk of orphaned vectors from a failed job, no eventual-consistency window between the relational store and the vector index.

**Tradeoff:** pgvector's HNSW index tops out around 100M vectors on commodity hardware before query latency degrades. A dedicated vector DB would scale further and offer features like tenant isolation and automatic replication. Accepted because DocExtract's target scale fits comfortably within pgvector's range, and operational simplicity outweighs edge-case scale ceiling.
