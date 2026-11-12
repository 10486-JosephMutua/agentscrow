"""Verdict receipts, signed with Ed25519 so ANYONE can verify them without trusting a shared secret.

The platform holds a private signing key; the matching public key is published at
``/.well-known/agentescrow-receipt-key.json``. A receipt contains scores, counts, PayPal ids and SHA-256 hashes (of the
deliverable and of the hidden tests), never the tests or the worker's code. ``scripts/verify_receipt.py`` checks a
receipt offline using only the public key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from agentescrow.domain.models import Job, JobState

logger = logging.getLogger(__name__)
ALGORITHM = "Ed25519"


def deliverable_hash(deliverable: dict[str, Any] | None) -> str | None:
    if deliverable is None:
        return None
    return hashlib.sha256(canonical_json(deliverable)).hexdigest()


def stabilize(value: Any) -> Any:
    """Make a receipt body canonicalize identically in every language: floats become fixed-point strings.

    Python writes ``1.0`` where JavaScript (and most other languages) read and write ``1``; a signature over the raw float would
    break the moment a receipt passed through such a client. Integers, strings, booleans and null are already portable.
    """
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, dict):
        return {str(key): stabilize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [stabilize(item) for item in value]
    return str(value)


def canonical_json(value: Any) -> bytes:
    """The exact bytes that are signed: sorted keys, no whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def key_id_for(public_key_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(public_key_b64)).hexdigest()[:16]


def verify_signature(public_key_b64: str, payload: Any, signature_b64: str) -> bool:
    """Check ``signature_b64`` over ``payload`` with a base64 raw Ed25519 public key. Never raises."""
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(base64.b64decode(signature_b64), canonical_json(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


class ReceiptSigner:
    """Holds the platform's Ed25519 key. Loaded from ``RECEIPT_SIGNING_KEY`` (base64 32-byte seed) or a key file that is
    created on first start (mode 0600). Keep the file: if it is lost, old receipts can still be verified with the old public key."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._key = private_key
        self.public_key_b64 = _b64(private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        self.key_id = key_id_for(self.public_key_b64)

    @classmethod
    def load(cls, *, seed_b64: str = "", key_path: Path | None = None) -> "ReceiptSigner":
        if seed_b64:
            return cls(Ed25519PrivateKey.from_private_bytes(base64.b64decode(seed_b64)))
        if key_path is None:
            logger.warning("No receipt signing key configured: using an EPHEMERAL key (receipts will not verify after a restart)")
            return cls(Ed25519PrivateKey.generate())
        if key_path.exists():
            return cls(Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_path.read_text().strip())))
        key = Ed25519PrivateKey.generate()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(_b64(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())))
        logger.info("Created a new receipt signing key at %s", key_path)
        return cls(key)

    def sign(self, payload: Any) -> str:
        return _b64(self._key.sign(canonical_json(payload)))

    def public_info(self) -> dict[str, str]:
        return {"alg": ALGORITHM, "key_id": self.key_id, "public_key": self.public_key_b64}


def build_receipt(job: Job, signer: ReceiptSigner, *, simulated: bool) -> dict[str, Any]:
    if job.state not in {JobState.SETTLED, JobState.VOIDED}:
        raise ValueError(f"Job is {job.state.value}; a receipt exists only for settled or voided jobs")
    verdict, decision = job.verdict, job.decision
    body: dict[str, Any] = {
        "job_id": job.job_id,
        "title": job.contract.specification.title,
        "template": job.template_id,
        "state": job.state.value,
        "simulated": simulated,
        "bounty_usd": str(job.contract.bounty_usd),
        "outcome": decision.outcome.value if decision else None,
        "reason": decision.reason if decision else None,
        "v_score": decision.v_score if decision else None,
        "capture_usd": str(decision.capture_amount) if decision else None,
        "platform_fee_usd": str(decision.platform_fee) if decision else None,
        "worker_payout_usd": str(decision.worker_payout) if decision else None,
        "buyer_charged_usd": str(decision.capture_amount) if decision else "0.00",
        "tiers": {
            "schema": {"valid": verdict.schema_check.valid, "errors": verdict.schema_check.errors},
            "integrity": {"ok": verdict.integrity.ok, "findings": verdict.integrity.findings},
            "sandbox": verdict.sandbox.model_dump(mode="json", exclude={"error"}) if verdict.sandbox else None,
            "semantic": verdict.semantic.model_dump(mode="json") if verdict.semantic else None,
            "skipped": verdict.tiers_skipped,
        }
        if verdict
        else None,
        "paypal": {
            "order_id": job.order_id,
            "authorization_id": job.authorization_id,
            "capture_id": job.capture_id,
            "payout_batch_id": job.payout_batch_id,
        },
        "deliverable_sha256": deliverable_hash(job.deliverable),
        "hidden_tests_sha256": job.contract.hidden_tests_sha256,
    }
    body = stabilize(body)
    return {"receipt": body, "signature": signer.sign(body), "alg": ALGORITHM, "key_id": signer.key_id}
