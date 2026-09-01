"""Which x402 endpoints ACTUALLY accept payment end-to-end?

Every public x402 census so far probes with an unpaid GET and reports whether
a 402 comes back. That measures *declaration*, not *function*. I now have a
working buyer, so I can measure the thing that actually matters to a buyer:
does the payment path work when you really pay?

This is deliberately cheap: candidates are $0.001-$0.008 each, so a full pass
costs cents. Results append to a JSON file so progress survives interruption.

Usage:
    python3 pay_census.py candidates.json out.json [--live]

Without --live it only probes challenges (free) and reports what it WOULD buy.
"""
import base64
import json
import os
import pathlib
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from eth_account import Account
from eth_account.messages import encode_typed_data

UA = {"user-agent": "clankerceo/1.0", "accept": "application/json"}
LIVE = "--live" in sys.argv
MAX_PRICE = float(os.environ.get("MAX_PRICE", "0.02"))


def load_key():
    v = os.environ.get("CEO_WALLET_PRIVATE_KEY")
    if v:
        return v
    for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
        line = line.strip()
        if line.startswith("CEO_WALLET_PRIVATE_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("no key")


ACCT = Account.from_key(load_key())

TYPES = {
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
}


def challenge(url):
    """Return (status, challenge_dict_or_None). Handles body OR header form."""
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=20)
        return r.status, None
    except urllib.error.HTTPError as e:
        if e.code != 402:
            return e.code, None
        raw = e.read().decode("utf-8", "replace")
        # Header FIRST: many servers return a valid but EMPTY body ({}) and put
        # the real challenge in `payment-required`. Parsing the body first
        # succeeds on {} and silently loses the challenge — that is what made
        # 19/60 look "unparseable" on my first pass.
        h = e.headers.get("payment-required")
        if h:
            try:
                ch = json.loads(base64.b64decode(h + "=="))
                if ch.get("accepts"):
                    return 402, ch
            except Exception:
                pass
        try:
            ch = json.loads(raw)
            return 402, (ch if ch.get("accepts") else None)
        except Exception:
            return 402, None
    except Exception:
        return 0, None


def declared_input(ch):
    """Read the method and example params the endpoint publishes itself.

    Endpoints advertise these in extensions.bazaar.info.input. Ignoring them
    is what made my first census measure my harness instead of the merchants.
    """
    info = (((ch.get("extensions") or {}).get("bazaar") or {})
            .get("info") or {}).get("input") or {}
    return (str(info.get("method") or "GET").upper(),
            info.get("queryParams") or {},
            info.get("bodyFields") or info.get("body") or None)


def pick_evm(ch):
    for a in ch.get("accepts") or []:
        net = str(a.get("network", ""))
        if net.endswith("8453") or net == "base":
            return a
    return None


def pay(url, ch, acc, method="GET", qp=None, body=None):
    now = int(time.time())
    va, vb = now - 60, now + int(acc.get("maxTimeoutSeconds", 300))
    nonce = "0x" + secrets.token_hex(32)
    amount = int(acc.get("amount") or acc.get("maxAmountRequired"))
    extra = acc.get("extra") or {"name": "USD Coin", "version": "2"}
    chain_id = int(str(acc["network"]).split(":")[1]) if ":" in str(
        acc["network"]) else 8453

    typed = {
        "types": TYPES,
        "primaryType": "TransferWithAuthorization",
        "domain": {"name": extra.get("name", "USD Coin"),
                   "version": extra.get("version", "2"),
                   "chainId": chain_id,
                   "verifyingContract": acc["asset"]},
        "message": {"from": ACCT.address, "to": acc["payTo"], "value": amount,
                    "validAfter": va, "validBefore": vb,
                    "nonce": bytes.fromhex(nonce[2:])},
    }
    sig = ACCT.sign_message(encode_typed_data(full_message=typed)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig

    payload = {
        "x402Version": 2, "scheme": "exact", "network": acc["network"],
        "accepted": dict(acc),
        "payload": {"signature": sig,
                    "authorization": {
                        "from": ACCT.address, "to": acc["payTo"],
                        "value": str(amount), "validAfter": str(va),
                        "validBefore": str(vb), "nonce": nonce}},
    }
    hdr = base64.b64encode(json.dumps(payload).encode()).decode()
    # Call the endpoint the way IT says to be called.
    target = url
    if qp:
        sep = "&" if "?" in target else "?"
        target = target + sep + urllib.parse.urlencode(qp)
    data = None
    heads = {**UA, "X-PAYMENT": hdr}
    if method == "POST":
        data = json.dumps(body or {}).encode()
        heads["content-type"] = "application/json"
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(target, headers=heads, data=data,
                                   method=method),
            timeout=60)
        body = r.read().decode("utf-8", "replace")
        settle = None
        pr = r.headers.get("payment-response")
        if pr:
            try:
                settle = json.loads(base64.b64decode(pr + "=="))
            except Exception:
                pass
        return {"paid_status": r.status, "settled": bool(
            (settle or {}).get("success")),
            "tx": (settle or {}).get("transaction"),
            "bytes": len(body), "sample": body[:180]}
    except urllib.error.HTTPError as e:
        return {"paid_status": e.code,
                "error": e.read().decode("utf-8", "replace")[:180]}
    except Exception as e:
        return {"paid_status": 0, "error": str(e)[:140]}


def main():
    cands = json.load(open(sys.argv[1]))
    outp = pathlib.Path(sys.argv[2])
    done = {}
    if outp.exists():
        done = {r["url"]: r for r in json.loads(outp.read_text())}

    results = list(done.values())
    for url in cands:
        if url in done:
            print(f"  skip (done) {url[:70]}")
            continue
        st, ch = challenge(url)
        rec = {"url": url, "challenge_status": st,
               "checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if st != 402 or not ch:
            rec["verdict"] = "NO_CHALLENGE" if st != 402 else "UNPARSEABLE"
        else:
            acc = pick_evm(ch)
            if not acc:
                rec["verdict"] = "NO_BASE_OFFER"
            else:
                price = int(acc.get("amount") or
                            acc.get("maxAmountRequired") or 0) / 1e6
                rec["price_usdc"] = price
                rec["payTo"] = acc.get("payTo")
                if price > MAX_PRICE:
                    rec["verdict"] = "TOO_EXPENSIVE_TO_TEST"
                elif not LIVE:
                    rec["verdict"] = "WOULD_BUY"
                else:
                    meth, qp, bodyf = declared_input(ch)
                    rec["method"] = meth
                    rec["params_used"] = list(qp)
                    out = pay(url, ch, acc, meth, qp, bodyf)
                    rec.update(out)
                    rec["verdict"] = ("PAYS_OK" if out.get("paid_status") == 200
                                      else f"PAY_FAILED_{out.get('paid_status')}")
        results.append(rec)
        print(f"  {rec['verdict']:22} {url[:66]}")
        outp.write_text(json.dumps(results, indent=1))
    print(f"\nwrote {len(results)} records -> {outp}")


if __name__ == "__main__":
    main()
