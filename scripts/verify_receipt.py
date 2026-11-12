"""Verify an AgentEscrow verdict receipt OFFLINE, using only the platform's public key.

    python -m scripts.verify_receipt receipt.json --public-key <base64>
    python -m scripts.verify_receipt receipt.json --server http://localhost:5000     # fetches the public key

Optionally check a revealed hidden-test file against the receipt's commitment:
    python -m scripts.verify_receipt receipt.json --public-key <base64> --hidden-tests tests.py
Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests

from agentescrow.domain.receipt import key_id_for, verify_signature


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("receipt", type=Path, help="receipt JSON as returned by GET /api/jobs/<id>/receipt")
    parser.add_argument("--public-key", help="base64 Ed25519 public key")
    parser.add_argument("--server", help="AgentEscrow base URL to fetch the public key from")
    parser.add_argument("--hidden-tests", type=Path, help="revealed hidden tests to check against the commitment")
    args = parser.parse_args()

    document = json.loads(args.receipt.read_text(encoding="utf-8"))
    key = args.public_key
    if not key and args.server:
        key = requests.get(f"{args.server.rstrip('/')}/.well-known/agentescrow-receipt-key.json", timeout=15).json()["public_key"]
    if not key:
        print("Give --public-key or --server")
        return 2

    ok = True
    print(f"key id        : {key_id_for(key)} (receipt says {document.get('key_id')})")
    valid = verify_signature(key, document["receipt"], document["signature"])
    print(f"signature     : {'VALID' if valid else 'INVALID'}")
    ok &= valid
    ok &= key_id_for(key) == document.get("key_id")
    if args.hidden_tests:
        digest = hashlib.sha256(args.hidden_tests.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        match = digest == document["receipt"].get("hidden_tests_sha256")
        print(f"hidden tests  : {'MATCH the commitment' if match else 'DO NOT MATCH the commitment'}")
        ok &= match
    receipt = document["receipt"]
    print(f"outcome       : {receipt.get('outcome')} (buyer charged ${receipt.get('buyer_charged_usd')}, worker paid ${receipt.get('worker_payout_usd')})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
