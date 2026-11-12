"""STEP 6: drive the running API through all three outcomes, the way the UI does.

    Terminal 1:  python -m agentescrow.api.app --inprocess
    Terminal 2:  python -m scripts.step6_demo_client

With PAYPAL_MODE=simulated the hold is approved automatically. With PAYPAL_MODE=sandbox the
script prints each approval URL and waits for you to approve it (use your sandbox buyer).
Each job gets its own buyer and worker tokens, exactly like two different browsers would.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests


def call(method: str, url: str, token: str | None = None, **kw):  # type: ignore[no-untyped-def]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.request(method, url, headers=headers, timeout=60, **kw)
    if response.status_code >= 400:
        raise SystemExit(f"{method} {url} -> {response.status_code}: {response.text}")
    return response.json()


def run_job(base: str, persona: str, mode: str) -> dict:
    print(f"\n=== {persona.upper()} worker ===")
    created = call("POST", f"{base}/api/jobs", json={"bounty_usd": "5.00"})
    jid, buyer = created["job"]["job_id"], created["token"]
    worker = call("POST", f"{base}/api/jobs/{jid}/accept", json={"worker_id": f"{persona}-worker", "worker_email": "payouts-simulator-receiver@paypal.com"})["token"]  # fmt: skip
    job = call("POST", f"{base}/api/jobs/{jid}/escrow", buyer)
    if mode == "sandbox":
        print(f"  Approve the PayPal hold here, then press Enter:\n  {job['approve_url']}")
        input("  > ")
        call("POST", f"{base}/api/jobs/{jid}/confirm-funding", buyer)
    else:
        requests.get(f"{base}/escrow/success", params={"job_id": jid}, allow_redirects=False, timeout=60)
    call("POST", f"{base}/api/jobs/{jid}/run", worker, json={"persona": persona})
    seen = 0
    while True:
        for event in call("GET", f"{base}/api/jobs/{jid}/events", params={"after": seen}):
            seen = event["id"]
            print(f"  {event['ts'][11:19]}  {event['kind']:<9} {event['message']}")
        job = call("GET", f"{base}/api/jobs/{jid}")
        if job["state"] in {"SETTLED", "VOIDED", "NEEDS_REVIEW"}:
            return job
        time.sleep(0.7)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    health = call("GET", f"{args.base}/api/health")
    print("API:", json.dumps(health))
    results = []
    for persona in ("honest", "sloppy", "cheater"):
        job = run_job(args.base, persona, health["paypal_mode"])
        receipt = call("GET", f"{args.base}/api/jobs/{job['job_id']}/receipt")["receipt"] if job["state"] != "NEEDS_REVIEW" else {}
        results.append((persona, job["state"], receipt.get("outcome"), receipt.get("buyer_charged_usd"), receipt.get("worker_payout_usd")))
    print("\n persona   state     outcome  buyer charged  worker paid")
    for persona, state, outcome, charged, paid in results:
        print(f" {persona:<9} {state:<9} {outcome!s:<8} ${charged!s:<13} ${paid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
