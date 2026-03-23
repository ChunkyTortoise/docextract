"""Agentic RAG endpoint — ReAct loop over document corpus."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
    from anthropic import AsyncAnthropic
    from app.config import settings
    from app.services.model_router import ModelRouter

    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    tools = RagTools(db=db, anthropic_client=anthropic_client)
    model_router = ModelRouter(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_seconds,
    )
    agent = AgenticRAG(tools=tools, model_router=model_router)

    return await agent.search(
        question=request.question,
        doc_ids=request.doc_ids,
        max_iterations=request.max_iterations,
    )
