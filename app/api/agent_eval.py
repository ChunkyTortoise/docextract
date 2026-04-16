"""Agent evaluation endpoint — POST /api/v1/agent-eval."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.middleware import get_api_key
from app.config import settings
from app.dependencies import get_db
from app.models.api_key import APIKey
from app.services.agent_evaluator import AgentEvalResult, AgentEvaluator
from app.services.agentic_rag import AgenticRAG, AgenticRAGResult

router = APIRouter(tags=["agent-eval"])


class AgentEvalRequest(BaseModel):
    question: str
    doc_ids: list[str] | None = None
    max_iterations: int = 3
    expected_tools: list[str] | None = None
    ground_truth_answer: str | None = None


class AgentEvalResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    rag_result: AgenticRAGResult
    eval_result: AgentEvalResult


@router.post("/agent-eval", response_model=AgentEvalResponse)
async def evaluate_agent(
    request: AgentEvalRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_api_key),
) -> AgentEvalResponse:
    """Run the agentic RAG pipeline, then evaluate decision quality."""
    if not settings.agent_eval_enabled:
        raise HTTPException(
            status_code=503,
            detail="Agent evaluation is disabled. Set AGENT_EVAL_ENABLED=true.",
        )

    from anthropic import AsyncAnthropic

    from app.services.model_router import ModelRouter
    from app.services.rag_tools import RagTools

    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    tools = RagTools(db=db, anthropic_client=anthropic_client)
    model_router = ModelRouter(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout=settings.circuit_breaker_recovery_seconds,
    )
    agentic_rag = AgenticRAG(tools=tools, model_router=model_router)

    rag_result = await agentic_rag.search(
        question=request.question,
        doc_ids=request.doc_ids,
        max_iterations=request.max_iterations,
    )

    evaluator = AgentEvaluator()
    eval_result = evaluator.evaluate(
        rag_result,
        expected_tools=request.expected_tools,
        ground_truth_answer=request.ground_truth_answer,
    )

    return AgentEvalResponse(rag_result=rag_result, eval_result=eval_result)
