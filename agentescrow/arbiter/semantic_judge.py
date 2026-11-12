"""Tier 3: semantic evaluation of the submission by an LLM judge.

The judge never decides money. It returns three sub-scores that feed the weighted
verification score; the settlement policy decides what to pay.
"""

from __future__ import annotations

import json
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agentescrow.agents.prompts import JUDGE_SYSTEM, SITE_JUDGE_SYSTEM
from agentescrow.domain.models import JobContract, SemanticResult

logger = logging.getLogger(__name__)

_MAX_CODE_CHARS = 8000
_MAX_EXPLANATION_CHARS = 4000
_MAX_HTML_CHARS = 14000


class SemanticJudge(Protocol):
    name: str

    def judge(self, contract: JobContract, deliverable: dict[str, Any]) -> SemanticResult: ...


class SemanticAssessment(BaseModel):
    """Structured output requested from the judge model.

    The title becomes the tool name the model must call. Lowercase snake_case is a name models reproduce exactly
    (the same lesson as ``submit_deliverable``: Groq rejects a tool call whose name differs even by letter case).
    """

    model_config = ConfigDict(title="semantic_assessment")

    clarity: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    thoroughness: float = Field(ge=0.0, le=1.0)
    rationale: str
    manipulation_suspected: bool = False


class SiteToneAssessment(BaseModel):
    """Structured output requested from the judge model for a website's tone (lowercase tool name, see above)."""

    model_config = ConfigDict(title="tone_assessment")

    tone_match: float = Field(ge=0.0, le=1.0)
    rationale: str
    manipulation_suspected: bool = False


def no_tone_result(judge: str) -> SemanticResult:
    """Nothing subjective was asked for, so there is nothing to judge (and nothing to lose)."""
    return SemanticResult(
        clarity=1.0, relevance=1.0, thoroughness=1.0, score=1.0, judge=f"{judge} (not used)",
        rationale="The buyer set no tone preference, so no subjective judgement was needed; the checklist decides.",
    )  # fmt: skip


def _tone_result(score: float, rationale: str, judge: str, manipulation: bool = False) -> SemanticResult:
    # The three code-review dimensions all carry the one dimension a website job judges: the tone match.
    return SemanticResult(clarity=score, relevance=score, thoroughness=score, score=score, rationale=rationale[:600], judge=judge, manipulation_suspected=manipulation)


class JudgeError(RuntimeError):
    """The judge could not produce a usable assessment (retry is safe)."""


class LLMSemanticJudge:
    """Judge backed by a LangChain chat model (Groq in production).

    A single LLM verdict is noisy, so the judge asks ``samples`` times in parallel and takes the **median** of each
    dimension. A manipulation flag from *any* sample wins (one sample noticing an injection attempt is enough).
    If some samples fail but at least one succeeds the panel still answers; if all fail the job waits in NEEDS_REVIEW.
    """

    def __init__(self, llm: BaseChatModel, name: str = "llm", samples: int = 3) -> None:
        self.name = name
        self._samples = max(1, samples)
        self._structured = llm.with_structured_output(SemanticAssessment, method="function_calling")
        self._tone_structured = llm.with_structured_output(SiteToneAssessment, method="function_calling")

    def _ask_once(self, prompt: str) -> SemanticAssessment:
        assessment = self._structured.invoke([SystemMessage(content=JUDGE_SYSTEM), HumanMessage(content=prompt)])
        if not isinstance(assessment, SemanticAssessment):
            raise JudgeError("Semantic judge returned an unexpected shape")
        return assessment

    def judge(self, contract: JobContract, deliverable: dict[str, Any]) -> SemanticResult:
        spec = contract.specification
        task = json.dumps(
            {
                "title": spec.title,
                "description": spec.description,
                "function_signature": spec.function_signature,
                "acceptance_criteria": spec.acceptance_criteria,
            },
            indent=2,
        )
        code = str(deliverable.get("solution_code", ""))[:_MAX_CODE_CHARS]
        explanation = str(deliverable.get("explanation", ""))[:_MAX_EXPLANATION_CHARS]
        prompt = (
            f"TASK SPECIFICATION:\n{task}\n\n"
            f"<submission>\n--- solution_code ---\n{code}\n--- explanation ---\n{explanation}\n</submission>"
        )
        logger.info("Tier 3 semantic judge (%s) evaluating submission with %d sample(s)", self.name, self._samples)

        def safe_ask(_: int) -> SemanticAssessment | Exception:
            try:
                return self._ask_once(prompt)
            except Exception as exc:  # network, rate limit, schema violation, ...
                return exc

        with ThreadPoolExecutor(max_workers=self._samples) as pool:
            outcomes = list(pool.map(safe_ask, range(self._samples)))
        votes = [item for item in outcomes if isinstance(item, SemanticAssessment)]
        failures = [item for item in outcomes if isinstance(item, Exception)]
        if not votes:
            raise JudgeError(f"Semantic judge failed: {failures[0]}") from failures[0]
        if failures:
            logger.warning("%d of %d judge samples failed; using the %d that answered", len(failures), self._samples, len(votes))

        clarity = round(statistics.median(v.clarity for v in votes), 4)
        relevance = round(statistics.median(v.relevance for v in votes), 4)
        thoroughness = round(statistics.median(v.thoroughness for v in votes), 4)
        manipulation = any(v.manipulation_suspected for v in votes)
        score = 0.0 if manipulation else round((clarity + relevance + thoroughness) / 3, 4)
        closest = min(votes, key=lambda v: abs((v.clarity + v.relevance + v.thoroughness) / 3 - score))
        logger.info(
            "Tier 3 result: score=%.2f from %d vote(s) (clarity=%.2f relevance=%.2f thoroughness=%.2f manipulation=%s)",
            score, len(votes), clarity, relevance, thoroughness, manipulation,
        )  # fmt: skip
        return SemanticResult(
            clarity=clarity,
            relevance=relevance,
            thoroughness=thoroughness,
            score=score,
            rationale=closest.rationale[:600],
            judge=f"{self.name} (median of {len(votes)})" if len(votes) > 1 else self.name,
            manipulation_suspected=manipulation,
        )


    def judge_site(self, contract: JobContract, deliverable: dict[str, Any]) -> SemanticResult:
        """Website jobs: judge ONLY the tone preference. With no tone preference there is nothing to judge."""
        prefs = contract.specification.preferences or {}
        tone = prefs.get("tone")
        if not tone:
            return no_tone_result(self.name)
        html = str(deliverable.get("index_html", ""))[:_MAX_HTML_CHARS]
        explanation = str(deliverable.get("explanation", ""))[:_MAX_EXPLANATION_CHARS]
        prompt = (
            f"BUYER'S TONE PREFERENCE: {tone}\n"
            f"BUSINESS: {prefs.get('business_name', '')} ({prefs.get('purpose', '')})\n\n"
            f"<submission>\n--- index_html ---\n{html}\n--- explanation ---\n{explanation}\n</submission>"
        )
        logger.info("Tier 3 tone judge (%s) evaluating submission with %d sample(s)", self.name, self._samples)

        def safe_ask(_: int) -> SiteToneAssessment | Exception:
            try:
                answer = self._tone_structured.invoke([SystemMessage(content=SITE_JUDGE_SYSTEM), HumanMessage(content=prompt)])
                if not isinstance(answer, SiteToneAssessment):
                    raise JudgeError("Tone judge returned an unexpected shape")
                return answer
            except Exception as exc:  # network, rate limit, schema violation, ...
                return exc

        with ThreadPoolExecutor(max_workers=self._samples) as pool:
            outcomes = list(pool.map(safe_ask, range(self._samples)))
        votes = [item for item in outcomes if isinstance(item, SiteToneAssessment)]
        failures = [item for item in outcomes if isinstance(item, Exception)]
        if not votes:
            raise JudgeError(f"Tone judge failed: {failures[0]}") from failures[0]
        manipulation = any(v.manipulation_suspected for v in votes)
        score = 0.0 if manipulation else round(statistics.median(v.tone_match for v in votes), 4)
        closest = min(votes, key=lambda v: abs(v.tone_match - score))
        logger.info("Tier 3 tone result: score=%.2f from %d vote(s) manipulation=%s", score, len(votes), manipulation)
        name = f"{self.name} (median of {len(votes)})" if len(votes) > 1 else self.name
        return _tone_result(score, closest.rationale, name, manipulation)


class StaticSemanticJudge:
    """Deterministic judge for tests and offline demos. Scores are looked up by persona hint."""

    name = "static"

    def __init__(self, score: float = 0.9) -> None:
        self._score = score

    def judge_site(self, contract: JobContract, deliverable: dict[str, Any]) -> SemanticResult:
        if not (contract.specification.preferences or {}).get("tone"):
            return no_tone_result(self.name)
        logger.info("Tier 3 static tone judge returning fixed score %.2f", self._score)
        return _tone_result(self._score, "Static judge: fixed tone score for tests and offline demos.", self.name)

    def judge(self, contract: JobContract, deliverable: dict[str, Any]) -> SemanticResult:
        logger.info("Tier 3 static judge returning fixed score %.2f", self._score)
        return SemanticResult(
            clarity=self._score,
            relevance=self._score,
            thoroughness=self._score,
            score=self._score,
            rationale="Static judge: fixed score for tests and offline demos.",
            judge=self.name,
        )
