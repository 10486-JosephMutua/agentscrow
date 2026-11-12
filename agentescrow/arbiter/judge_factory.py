"""Chooses the semantic judge implementation from settings."""

from __future__ import annotations

from agentescrow.agents.factory import build_chat_model
from agentescrow.arbiter.semantic_judge import LLMSemanticJudge, SemanticJudge, StaticSemanticJudge
from agentescrow.config import Settings


def build_judge(settings: Settings) -> SemanticJudge:
    if settings.semantic_judge == "static":
        return StaticSemanticJudge()
    model = build_chat_model(settings)
    return LLMSemanticJudge(model, name=f"groq:{getattr(model, 'model_name', settings.groq_model)}", samples=settings.judge_samples)
