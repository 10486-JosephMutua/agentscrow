"""Ed25519 receipts that anyone can verify, the public key endpoint, offline verification, and the discovery card."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentescrow.api.app import create_app
from agentescrow.domain.receipt import ReceiptSigner, verify_signature

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settled(api_parts):
    settings, service, runner = api_parts
    app = create_app(settings, service, runner)
    client = app.test_client(use_cookies=False)
    created = client.post("/api/jobs", json={"bounty_usd": "5.00"}).get_json()
    jid, buyer = created["job"]["job_id"], {"Authorization": f"Bearer {created['token']}"}
    client.post(f"/api/jobs/{jid}/accept", json={"worker_id": "w", "worker_email": "w@example.com"})
    client.post(f"/api/jobs/{jid}/escrow", headers=buyer)
    client.get(f"/escrow/success?job_id={jid}")
    client.post(f"/api/jobs/{jid}/run", json={"persona": "honest"}, headers=buyer)
    deadline = time.time() + 40
    while client.get(f"/api/jobs/{jid}").get_json()["state"] != "SETTLED" and time.time() < deadline:
        time.sleep(0.2)
    return client, jid


def test_the_receipt_verifies_against_the_published_public_key(settled):
    client, jid = settled
    document = client.get(f"/api/jobs/{jid}/receipt").get_json()
    key = client.get("/.well-known/agentescrow-receipt-key.json").get_json()
    assert document["alg"] == key["alg"] == "Ed25519" and document["key_id"] == key["key_id"]
    assert verify_signature(key["public_key"], document["receipt"], document["signature"])
    assert document["receipt"]["hidden_tests_sha256"] and document["receipt"]["template"] == "rle"


def test_any_change_to_a_receipt_breaks_the_signature(settled):
    client, jid = settled
    document = client.get(f"/api/jobs/{jid}/receipt").get_json()
    key = client.get("/.well-known/agentescrow-receipt-key.json").get_json()["public_key"]
    forged = json.loads(json.dumps(document))
    forged["receipt"]["worker_payout_usd"] = "9999.00"
    assert not verify_signature(key, forged["receipt"], document["signature"])
    assert client.post("/api/receipts/verify", json=document).get_json()["valid"] is True
    assert client.post("/api/receipts/verify", json=forged).get_json()["valid"] is False
    assert client.post("/api/receipts/verify", json={"nonsense": 1}).get_json()["valid"] is False


def test_the_offline_verifier_script(settled, tmp_path):
    client, jid = settled
    document = client.get(f"/api/jobs/{jid}/receipt").get_json()
    key = client.get("/.well-known/agentescrow-receipt-key.json").get_json()["public_key"]
    revealed = client.get(f"/api/jobs/{jid}/hidden-tests").get_json()
    receipt_file, tests_file = tmp_path / "receipt.json", tmp_path / "tests.py"
    receipt_file.write_text(json.dumps(document))
    tests_file.write_text(revealed["tests"], encoding="utf-8")

    def run(*extra):
        return subprocess.run([sys.executable, "-m", "scripts.verify_receipt", str(receipt_file), "--public-key", key, *extra], cwd=ROOT, capture_output=True, text=True)

    good = run("--hidden-tests", str(tests_file))
    assert good.returncode == 0 and "VALID" in good.stdout and "MATCH the commitment" in good.stdout
    tests_file.write_text(revealed["tests"] + "\n# edited", encoding="utf-8")
    assert run("--hidden-tests", str(tests_file)).returncode == 1
    document["receipt"]["buyer_charged_usd"] = "0.00"
    receipt_file.write_text(json.dumps(document))
    assert "INVALID" in run().stdout and run().returncode == 1


def test_hidden_tests_endpoint_is_gated_until_the_verdict(api_parts):
    settings, service, runner = api_parts
    client = create_app(settings, service, runner).test_client(use_cookies=False)
    jid = client.post("/api/jobs", json={}).get_json()["job"]["job_id"]
    assert client.get(f"/api/jobs/{jid}/hidden-tests").status_code == 409


def test_signing_keys_persist_and_can_come_from_the_environment(tmp_path):
    first = ReceiptSigner.load(key_path=tmp_path / "k")
    again = ReceiptSigner.load(key_path=tmp_path / "k")
    assert first.key_id == again.key_id and (tmp_path / "k").stat().st_mode & 0o077 == 0
    import base64

    seed = base64.b64encode(b"\x01" * 32).decode()
    assert ReceiptSigner.load(seed_b64=seed).key_id == ReceiptSigner.load(seed_b64=seed).key_id != first.key_id


def test_the_discovery_card_describes_the_service_honestly(api_parts):
    settings, service, runner = api_parts
    card = create_app(settings, service, runner).test_client().get("/.well-known/agent-card.json").get_json()
    assert card["name"] == "AgentEscrow" and {s["id"] for s in card["skills"]} >= {"post-escrowed-job", "accept-and-deliver", "verify-verdict"}
    assert "not through A2A message endpoints" in card["description"]
    assert card["x-agentescrow"]["receipt_public_key"].endswith("/.well-known/agentescrow-receipt-key.json")


def test_a_receipt_survives_a_round_trip_through_javascript(settled):
    """JavaScript reads 1.0 as 1. A signature over raw floats broke here; the signed body must be float-free."""
    client, jid = settled
    document = client.get(f"/api/jobs/{jid}/receipt").get_json()

    def walk(value):
        if isinstance(value, float):
            raise AssertionError(f"a float leaked into the signed body: {value}")
        for item in value.values() if isinstance(value, dict) else value if isinstance(value, list) else []:
            walk(item)

    walk(document["receipt"])

    def as_javascript_would(text):  # JSON.parse then JSON.stringify: integral floats lose their ".0"
        return json.loads(text, parse_float=lambda raw: int(float(raw)) if float(raw).is_integer() else float(raw))

    roundtripped = as_javascript_would(json.dumps(document))
    key = client.get("/.well-known/agentescrow-receipt-key.json").get_json()["public_key"]
    assert verify_signature(key, roundtripped["receipt"], roundtripped["signature"])
    assert client.post("/api/receipts/verify", json=roundtripped).get_json()["valid"] is True
    assert document["receipt"]["v_score"] == "0.9700" and document["receipt"]["tiers"]["sandbox"]["score"] == "1.0000"
