"""Agentic RAG endpoints — ReAct loop over document corpus.

Supports both batch (POST /agent-search) and streaming (POST /agent-search/stream)
execution. The streaming endpoint emits Server-Sent Events with real-time
Think → Act → Observe reasoning steps.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.auth.middleware import get_api_key
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.services.agentic_rag import AgenticRAG, AgenticRAGResult
from app.services.rag_tools import RagTools

router = APIRouter(tags=["agent-search"])


class AgentSearchRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language question to answer")
    doc_ids: list[str] | None = Field(
        default=None,
        description="Optional list of document UUIDs to restrict search to",
    )
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum ReAct iterations before returning best answer",
    )


def _build_agent(db: AsyncSession) -> AgenticRAG:
    """Construct an AgenticRAG instance with default wiring."""
    from anthropic import AsyncAnthropic
    from app.config import settings
    from app.services.model_router import ModelRouter

    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    tools = RagTools(db=db, anthropic_client=anthropic_client)
    model_router = ModelRouter(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_seconds,
    )
    return AgenticRAG(tools=tools, model_router=model_router)


@router.post("/agent-search", response_model=AgenticRAGResult)
async def agent_search(
    request: AgentSearchRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> AgenticRAGResult:
    """Run an agentic ReAct RAG loop over the document corpus.

    The agent iteratively decides which search tool to call (vector, BM25,
    hybrid, metadata lookup, or rerank), executes it, self-assesses
    confidence, and repeats until confident or max_iterations is reached.

    Returns the final answer, source passages, and a full reasoning trace.
    """
    agent = _build_agent(db)
    return await agent.search(
        question=request.question,
        doc_ids=request.doc_ids,
        max_iterations=request.max_iterations,
    )


@router.post("/agent-search/stream")
async def agent_search_stream(
    request: AgentSearchRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> EventSourceResponse:
    """Stream ReAct reasoning steps as Server-Sent Events.

    Emits ``event: step`` with a ReasoningStep JSON payload after each
    Think → Act → Observe cycle, followed by a final ``event: done``
    carrying the complete AgenticRAGResult.
    """
    agent = _build_agent(db)

    async def event_generator():
        async for stream_event in agent.search_stream(
            question=request.question,
            doc_ids=request.doc_ids,
            max_iterations=request.max_iterations,
        ):
            yield {
                "event": stream_event.event_type,
                "data": json.dumps(
                    stream_event.model_dump(exclude_none=True),
                    default=str,
                ),
            }

    return EventSourceResponse(event_generator())


class SynthesizeRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Question to answer across multiple documents")
    doc_ids: list[str] = Field(..., min_length=1, description="Document UUIDs to synthesize across")


@router.post("/agent-search/synthesize")
async def agent_search_synthesize(
    request: SynthesizeRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
):
    """Synthesize an answer across multiple documents using map-reduce RAG.

    For each document, extracts relevant passages (map phase), then combines
    per-document evidence into a unified answer with citations (reduce phase).
    """
    from app.services.multi_doc_synthesizer import MultiDocSynthesizer

    agent = _build_agent(db)
    synthesizer = MultiDocSynthesizer(
        tools=agent._tools,
        model_router=agent._router,
    )
    return await synthesizer.synthesize(
        question=request.question,
        doc_ids=request.doc_ids,
    )
