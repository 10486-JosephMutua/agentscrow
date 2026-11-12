"""STEP 4: run the three worker personas through the arbiter and settlement policy. Offline.

    python -m scripts.step4_arbiter_demo            # static judge, no keys needed
    python -m scripts.step4_arbiter_demo --groq     # use the real Groq judge (needs GROQ_API_KEY)
"""

from __future__ import annotations

import argparse
import asyncio

from agentescrow.arbiter.arbiter import Arbiter
from agentescrow.arbiter.judge_factory import build_judge
from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
from agentescrow.domain.settlement import decide_settlement
from agentescrow.samples import SCRIPTED_DELIVERABLES, build_sample_contract
from scripts._common import bootstrap


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groq", action="store_true", help="use the Groq LLM judge instead of the static one")
    args = parser.parse_args()
    settings, log = bootstrap("step4-arbiter")
    judge = build_judge(settings) if args.groq else StaticSemanticJudge(0.9)
    arbiter = Arbiter(settings, judge)
    log.info("STEP 4: arbitrating three personas (judge=%s, sandbox=%s)", judge.name, settings.sandbox_backend)

    print(f"\n{'persona':<9} {'schema':<7} {'integrity':<10} {'hidden tests':<13} {'judge':<6} {'V':<5} outcome   capture   worker")
    for persona, deliverable in SCRIPTED_DELIVERABLES.items():
        contract, hidden = build_sample_contract()
        verdict = await arbiter.evaluate(contract, hidden, deliverable)
        decision = decide_settlement(verdict, bounty=contract.bounty_usd, fee_rate=settings.platform_fee_rate)
        sb = f"{verdict.sandbox.passed}/{verdict.sandbox.total}" if verdict.sandbox else "not run"
        sem = f"{verdict.semantic.score:.2f}" if verdict.semantic else "-"
        print(f"{persona:<9} {'PASS' if verdict.schema_check.valid else 'FAIL':<7} {'PASS' if verdict.integrity.ok else 'FAIL':<10} "
              f"{sb:<13} {sem:<6} {verdict.v_score:<5.2f} {decision.outcome.value:<9} ${decision.capture_amount:<8} ${decision.worker_payout}")  # fmt: skip
        log.info("  %s: %s", persona, decision.reason)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
