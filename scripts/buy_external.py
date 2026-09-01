"""Buy x402scan's gated market data with a real x402 payment on Base.

Two purposes:
  1. Get the actual buyer/merchant data — who spends money on x402 right now
     and what they buy. Revealed demand beats guessing.
  2. Be a real buyer myself. Everything I have settled so far was my own money
     round-tripping; this is an actual outbound purchase from a third party.

Signs an EIP-3009 authorization for the exact amount and submits it.
"""
import base64
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request

from eth_account import Account
from eth_account.messages import encode_typed_data

PATH = sys.argv[1] if len(sys.argv) > 1 else "/api/x402/buyers?limit=25"
URL = "https://www.x402scan.com" + PATH
UA = {"user-agent": "clankerceo/1.0", "accept": "application/json"}


def load_key():
    v = os.environ.get("CEO_WALLET_PRIVATE_KEY")
    if v:
        return v
    for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
        line = line.strip()
        if line.startswith("CEO_WALLET_PRIVATE_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("no key")


acct = Account.from_key(load_key())
print("paying as:", acct.address)

# 1. Get the challenge (x402scan puts it in a HEADER, not the body).
req = urllib.request.Request(URL, headers=UA)
try:
    r = urllib.request.urlopen(req, timeout=30)
    print("already open, no payment needed:", r.status)
    print(r.read().decode()[:600])
    sys.exit(0)
except urllib.error.HTTPError as e:
    if e.code != 402:
        raise SystemExit(f"unexpected {e.code}: {e.read()[:200]}")
    hdr = e.headers.get("payment-required")
    ch = json.loads(base64.b64decode(hdr + "=="))

acc = ch["accepts"][0]
amount = int(acc["amount"])
print(f"price: {amount/1e6} USDC on {acc['network']} -> {acc['payTo']}")

# 2. Sign an EIP-3009 TransferWithAuthorization for that exact amount.
now = int(time.time())
nonce = "0x" + secrets.token_hex(32)
# validAfter must be in the PAST (some verifiers reject exactly-now), and the
# reference x402 client sends these as decimal strings.
valid_after = now - 60
valid_before = now + acc.get("maxTimeoutSeconds", 300)
auth = {
    "from": acct.address,
    "to": acc["payTo"],
    "value": str(amount),
    "validAfter": str(valid_after),
    "validBefore": str(valid_before),
    "nonce": nonce,
}
typed = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ],
    },
    "primaryType": "TransferWithAuthorization",
    "domain": {
        "name": acc["extra"]["name"],
        "version": acc["extra"]["version"],
        "chainId": int(acc["network"].split(":")[1]),
        "verifyingContract": acc["asset"],
    },
    "message": {
        "from": acct.address,
        "to": acc["payTo"],
        "value": amount,
        "validAfter": valid_after,
        "validBefore": valid_before,
        "nonce": bytes.fromhex(nonce[2:]),
    },
}
sig = acct.sign_message(encode_typed_data(full_message=typed)).signature.hex()
if not sig.startswith("0x"):
    sig = "0x" + sig

# Try several payload shapes: servers differ on v1 vs v2 and on whether they
# want the resource echoed. Learned this the hard way with PayAI, whose v2 EVM
# path 500s while v1 settles fine.
# The `accepted` field is REQUIRED on x402 v2 payloads: it echoes which of the
# seller's offered accepts the buyer chose. CDP rejects payloads without it
# ("x402V2PaymentPayload requires 'accepted'"), and so do real sellers. My own
# Worker never enforced it, which is why my self-tests passed while every
# outbound purchase failed.
accepted = dict(acc)

SHAPES = [
    ("v2+accepted", {"x402Version": 2, "scheme": "exact",
                     "network": acc["network"], "accepted": accepted,
                     "payload": {"signature": sig, "authorization": auth},
                     "resource": ch.get("resource")}),
    ("v2+accepted bare", {"x402Version": 2, "scheme": "exact",
                          "network": acc["network"], "accepted": accepted,
                          "payload": {"signature": sig,
                                      "authorization": auth}}),
    ("v2+resource", {"x402Version": 2, "scheme": "exact",
                     "network": acc["network"],
                     "payload": {"signature": sig, "authorization": auth},
                     "resource": ch.get("resource")}),
    ("v2 bare", {"x402Version": 2, "scheme": "exact",
                 "network": acc["network"],
                 "payload": {"signature": sig, "authorization": auth}}),
    ("v1 base", {"x402Version": 1, "scheme": "exact", "network": "base",
                 "payload": {"signature": sig, "authorization": auth}}),
]


def attempt(label, payload):
    hdr = base64.b64encode(json.dumps(payload).encode()).decode()
    req = urllib.request.Request(URL, headers={**UA, "X-PAYMENT": hdr})
    try:
        return label, urllib.request.urlopen(req, timeout=60), None
    except urllib.error.HTTPError as e:
        return label, None, e


for label, payload in SHAPES:
    lab, r, err = attempt(label, payload)
    if r is not None:
        print(f"\n[{lab}] accepted")
        break
    body = err.read().decode("utf-8", "replace")[:200]
    print(f"[{lab}] {err.code} {body}")
else:
    raise SystemExit("all payload shapes rejected")

try:
    body = r.read().decode("utf-8", "replace")
    print(f"\n=== HTTP {r.status} PAID ===")
    pr = r.headers.get("payment-response") or r.headers.get("PAYMENT-RESPONSE")
    if pr:
        try:
            print("settlement:", json.dumps(json.loads(base64.b64decode(pr + "==")))[:300])
        except Exception:
            print("settlement hdr:", pr[:160])
    print(body[:3000])
except urllib.error.HTTPError as e:
    print(f"\n=== REJECTED {e.code} ===")
    print(e.read().decode("utf-8", "replace")[:600])
