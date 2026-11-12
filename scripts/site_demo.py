"""Website demo: three workers build the same site, and the arbiter checks it against the buyer's preferences.

    python -m scripts.site_demo                 # static judge: no keys, no Docker, no PayPal needed
    python -m scripts.site_demo --groq          # use the real Groq judge for the tone preference
    python -m scripts.site_demo --prefs my.json # your own preferences (same shape as SAMPLE_PREFERENCES below)

It writes ./site_demo/report.html (plus one .html per worker) and opens the report in your browser. In the report,
click "Run in browser" under any worker to see the website it delivered, in a sandboxed frame, next to the
preference checklist the arbiter produced for it.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import webbrowser
from decimal import Decimal
from pathlib import Path

from agentescrow.arbiter.arbiter import Arbiter
from agentescrow.arbiter.judge_factory import build_judge
from agentescrow.arbiter.semantic_judge import StaticSemanticJudge
from agentescrow.domain.settlement import decide_settlement
from agentescrow.sitecheck import preview_document, scripted_site_deliverable
from agentescrow.sites import SitePreferences, build_site_task, lint_site_task
from scripts._common import bootstrap

SAMPLE_PREFERENCES = {
    "business_name": "Lens & Light Studio",
    "purpose": "Portfolio website for a wedding and portrait photographer",
    "sections": ["hero", "about", "gallery", "pricing", "contact"],
    "primary_color": "blue",
    "theme": "dark",
    "contact_fields": ["name", "email", "message"],
    "include_text": ["Book a free consultation"],
    "tone": "Minimal and professional",
}
PERSONAS = ("honest", "sloppy", "cheater")
_BADGE = {"FULL": "#16a34a", "PARTIAL": "#d97706", "VOID": "#dc2626"}

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentEscrow: website demo</title>
<style>
body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#f4f5f7;color:#16202e}
header{padding:28px 5vw;background:#0b1220;color:#fff}header h1{margin:0 0 6px}header p{margin:0;color:#9fb0c8}
.wrap{padding:24px 5vw;display:grid;gap:24px}
.card{background:#fff;border:1px solid #dde2ea;border-radius:14px;padding:20px}
.top{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
.badge{color:#fff;font-weight:700;border-radius:999px;padding:4px 14px}
.cols{display:grid;grid-template-columns:minmax(300px,1fr) minmax(320px,1.4fr);gap:20px;margin-top:14px}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
ul{list-style:none;margin:0;padding:0;display:grid;gap:6px}
li{padding:8px 10px;border-radius:8px;font-size:.92rem}li.ok{background:#e8f7ee;color:#14532d}li.bad{background:#fdecec;color:#7f1d1d}
li small{display:block;opacity:.85}
.tools{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
button{border:0;border-radius:8px;padding:9px 16px;font-weight:700;cursor:pointer;background:#2563eb;color:#fff}
button.alt{background:#e5e9f0;color:#16202e}
iframe{width:100%;height:560px;border:1px solid #cfd6e2;border-radius:10px;background:#fff;display:block;margin:0 auto;transition:width .2s}
.empty{height:560px;border:2px dashed #cfd6e2;border-radius:10px;display:grid;place-items:center;color:#6b7686}
.note{color:#6b7686;font-size:.9rem}
</style></head><body>
<header><h1>Website jobs, checked against the buyer's preferences</h1><p>__SUBTITLE__</p></header>
<div class="wrap">__CARDS__</div>
<script>
document.querySelectorAll('[data-run]').forEach(function(btn){
  btn.addEventListener('click',function(){
    var card=btn.closest('.card'),frame=card.querySelector('iframe'),empty=card.querySelector('.empty');
    if(frame.dataset.url){URL.revokeObjectURL(frame.dataset.url);}
    var url=URL.createObjectURL(new Blob([btn.dataset.doc],{type:'text/html'}));
    frame.dataset.url=url;frame.src=url;frame.style.display='block';if(empty)empty.style.display='none';
  });
});
document.querySelectorAll('[data-width]').forEach(function(btn){
  btn.addEventListener('click',function(){var card=btn.closest('.card');card.querySelector('iframe').style.width=btn.dataset.width;});
});
</script></body></html>
"""


def _card(persona: str, deliverable: dict, verdict, decision) -> str:
    checklist = "".join(
        f'<li class="{"ok" if item.passed else "bad"}">{"&#10003;" if item.passed else "&#10007;"} {html.escape(item.label)}'
        f"<small>{html.escape(item.detail)}</small></li>"
        for item in (verdict.checklist or [])
    )
    findings = "".join(f'<li class="bad">&#10007; {html.escape(f)}</li>' for f in verdict.integrity.findings)
    if not checklist and not findings:
        checklist = '<li class="bad">The page was rejected before any preference check ran.</li>'
    sb = verdict.sandbox
    summary = (
        f"Preference checks: {sb.passed}/{sb.total} passed &middot; " if sb else "Preference checks: not run &middot; "
    ) + (f"tone judge {verdict.semantic.score:.2f}" if verdict.semantic else "tone judge: not run")
    doc = html.escape(preview_document(deliverable["index_html"]), quote=True)
    return f"""<section class="card">
<div class="top"><h2 style="margin:0">{persona.title()} worker</h2>
<span class="badge" style="background:{_BADGE[decision.outcome.value]}">{decision.outcome.value} &middot; V = {verdict.v_score:.2f}</span></div>
<p class="note">{html.escape(decision.reason)}<br>{summary}<br>Worker pays out ${decision.worker_payout} of ${decision.capture_amount} captured.</p>
<div class="cols"><div><h3>Integrity gate: {"passed" if verdict.integrity.ok else "FAILED"}</h3><ul>{findings}</ul>
<h3>Checklist</h3><ul>{checklist}</ul></div>
<div><div class="tools"><button data-run data-doc="{doc}">&#9654; Run in browser</button>
<button class="alt" data-width="375px">Phone</button><button class="alt" data-width="768px">Tablet</button><button class="alt" data-width="100%">Desktop</button></div>
<div class="empty">Click &ldquo;Run in browser&rdquo; to see this worker's website</div>
<iframe title="{persona} worker website" sandbox="" style="display:none"></iframe></div></div></section>"""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groq", action="store_true", help="use the Groq LLM judge for the tone preference")
    parser.add_argument("--prefs", type=Path, help="JSON file with your own preferences")
    parser.add_argument("--no-open", action="store_true", help="write the report but do not open the browser")
    parser.add_argument("--out", type=Path, default=Path("site_demo"))
    args = parser.parse_args()

    settings, log = bootstrap("site-demo")
    raw = json.loads(args.prefs.read_text(encoding="utf-8")) if args.prefs else SAMPLE_PREFERENCES
    prefs = SitePreferences.model_validate(raw)
    report = lint_site_task(prefs)
    for check in report.checks:
        log.info("lint: %s %s", "PASS" if check.passed else "FAIL", check.name)
    if not report.ok:
        log.error("The preferences did not pass the task lint")
        return 1

    judge = build_judge(settings) if args.groq else StaticSemanticJudge(0.9)
    arbiter = Arbiter(settings, judge)
    args.out.mkdir(parents=True, exist_ok=True)
    cards: list[str] = []
    print(f"\n{'worker':<9} {'integrity':<10} {'checks':<8} {'tone':<6} {'V':<5} outcome   worker paid")
    for persona in PERSONAS:
        built = build_site_task(prefs, Decimal("5.00"), 3600)
        deliverable = scripted_site_deliverable(prefs.model_dump(), persona)
        (args.out / f"{persona}.html").write_text(deliverable["index_html"], encoding="utf-8")
        verdict = await arbiter.evaluate(built.contract, built.hidden_tests, deliverable)
        decision = decide_settlement(verdict, bounty=built.contract.bounty_usd, fee_rate=settings.platform_fee_rate)
        sb = f"{verdict.sandbox.passed}/{verdict.sandbox.total}" if verdict.sandbox else "not run"
        tone = f"{verdict.semantic.score:.2f}" if verdict.semantic else "-"
        print(f"{persona:<9} {'PASS' if verdict.integrity.ok else 'FAIL':<10} {sb:<8} {tone:<6} {verdict.v_score:<5.2f} {decision.outcome.value:<9} ${decision.worker_payout}")
        cards.append(_card(persona, deliverable, verdict, decision))

    subtitle = f"{prefs.business_name}: {prefs.purpose}. Sections: {', '.join(prefs.sections)}. Accent: {prefs.primary_color}. Theme: {prefs.theme}."
    target = (args.out / "report.html").resolve()
    target.write_text(_PAGE.replace("__SUBTITLE__", html.escape(subtitle)).replace("__CARDS__", "\n".join(cards)), encoding="utf-8")
    print(f"\nReport written to {target}")
    if not args.no_open:
        webbrowser.open(target.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
