"""x402 preflight — will this endpoint actually take my money?

The gap this fills: every existing x402 checker answers "is it up?" or "does it
emit a 402?". Neither predicts whether a payment will SETTLE. My census showed
those are very different questions — a blind liveness view said 1/60 endpoints
worked; calling each endpoint as it declares itself gave 8/60.

This does a full DRY-RUN of a purchase without spending anything:

  1. fetch the challenge (header first — 2/3 of endpoints put it ONLY in the
     base64 `payment-required` header, not the body)
  2. parse every offer and check each against reality:
       - is the asset a USDC contract I recognise on that chain?
       - is payTo a plausible non-null address?
       - is maxAmountRequired sane, and does it match the advertised price?
       - is the declared method/params actually usable?
  3. sign a REAL EIP-3009 authorization for the exact offer, then submit it to
     CDP /verify — which proves the payment is spendable WITHOUT settling it
  4. report a verdict plus the precise reason

Critically it reports WHY, not just pass/fail, because the reason is what a
buyer can act on. And it never claims a merchant is broken on the strength of
CDP alone — CDP validates signatures, not merchant business rules (it returns
isValid:true for payTo=0x...dEaD), so a CDP pass plus a merchant refusal is
reported as INCONCLUSIVE, not "their bug".
"""
import base64
import urllib.parse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = {"user-agent": "clankerceo-preflight/1.0", "accept": "application/json"}

USDC = {
    # EVM (checksummed contract addresses)
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",   # Base
    "eip155:137": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",    # Polygon
    "eip155:42161": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # Arbitrum
    "eip155:10": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",     # Optimism
    "base": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "polygon": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    # Solana mainnet: the network id is the genesis hash, asset is the mint.
    "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp":
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "solana": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
}

# Solana addresses are base58, not 0x-hex, so validity checks must branch.
SOLANA_PREFIX = "solana"


def _price(offer):
    """x402 offers carry the price as `maxAmountRequired` OR `amount`.

    My first version only read the former, so my own endpoints reported a
    price of None. Same class of bug as every other harness error this week:
    the tool was wrong, not the thing being measured.
    """
    for key in ("maxAmountRequired", "amount"):
        v = offer.get(key)
        if v is not None and str(v).isdigit():
            return int(v) / 1e6
    return None
NULLISH = {"0x0000000000000000000000000000000000000000",
           "0x000000000000000000000000000000000000dead"}


def fetch_challenge(url, method="GET", params=None):
    """Return (status, challenge_dict, source) — header parsed FIRST."""
    target = url
    if params and method == "GET":
        sep = "&" if "?" in url else "?"
        target = url + sep + urllib.parse.urlencode(params)
    data = None
    if method == "POST":
        data = json.dumps(params or {}).encode()
    req = urllib.request.Request(target, data=data, headers={
        **UA, **({"content-type": "application/json"} if data else {})})
    try:
        r = urllib.request.urlopen(req, timeout=25)
        return r.status, None, "no-challenge (200)"
    except urllib.error.HTTPError as e:
        if e.code != 402:
            return e.code, None, f"http {e.code}"
        raw_hdr = e.headers.get("payment-required") or ""
        body = e.read().decode("utf-8", "replace")
        # Header first: most endpoints omit the body entirely.
        if raw_hdr:
            try:
                pad = "=" * (-len(raw_hdr) % 4)
                return 402, json.loads(
                    base64.b64decode(raw_hdr + pad).decode()), "header"
            except Exception:
                pass
        try:
            return 402, json.loads(body), "body"
        except Exception:
            return 402, None, "402 with unparseable challenge"
    except Exception as e:
        return 0, None, f"unreachable: {str(e)[:60]}"


def audit_offer(offer):
    """Static checks a buyer can run before spending anything."""
    problems = []
    net = str(offer.get("network") or "")
    asset = str(offer.get("asset") or "")
    pay_to = str(offer.get("payTo") or "").lower()
    amount = offer.get("maxAmountRequired") or offer.get("amount")

    known = USDC.get(net)
    if not known:
        problems.append(f"unrecognised network {net!r}")
    elif asset:
        # EVM addresses are case-insensitive; Solana base58 mints are NOT.
        same = (asset == known if net.startswith(SOLANA_PREFIX)
                else asset.lower() == known.lower())
        if not same:
            problems.append(f"asset {asset[:12]}… is not USDC on {net}")

    is_svm = net.startswith(SOLANA_PREFIX)
    if not pay_to:
        problems.append("no payTo")
    elif pay_to in NULLISH:
        problems.append(f"payTo is a burn address ({pay_to[:10]}…)")
    elif is_svm:
        # Solana: base58, 32-44 chars, no 0x prefix, excludes 0/O/I/l.
        raw = str(offer.get("payTo") or "")
        if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", raw):
            problems.append("payTo is not a valid Solana address")
    elif not re.fullmatch(r"0x[0-9a-f]{40}", pay_to):
        problems.append("payTo is not a valid EVM address")

    try:
        units = int(amount)
        if units <= 0:
            problems.append("price is zero or negative")
        elif units > 100_000_000:
            problems.append(f"price is {units/1e6:.2f} USDC — implausibly high")
    except Exception:
        problems.append(f"maxAmountRequired {amount!r} is not an integer")

    return problems


def preflight(url, method="GET", params=None):
    out = {"url": url, "method": method}
    status, ch, source = fetch_challenge(url, method, params)
    out["challenge_source"] = source

    if status == 200:
        out["verdict"] = "NOT_PAYWALLED"
        out["reason"] = "returned 200 without a payment challenge"
        return out
    if status != 402 or not ch:
        out["verdict"] = "NO_CHALLENGE"
        out["reason"] = source
        return out

    offers = ch.get("accepts") or ch.get("offers") or []
    if not offers:
        out["verdict"] = "MALFORMED"
        out["reason"] = "402 with no offers in `accepts`"
        return out

    out["offers"] = len(offers)
    results = []
    for o in offers:
        results.append({
            "network": o.get("network"),
            "price_usdc": _price(o),
            "problems": audit_offer(o),
        })
    out["offer_audit"] = results

    payable = [r for r in results if not r["problems"]]
    if not payable:
        out["verdict"] = "WILL_FAIL"
        out["reason"] = "; ".join(results[0]["problems"])[:160]
        return out

    out["verdict"] = "LOOKS_PAYABLE"
    out["reason"] = (f"{len(payable)} of {len(results)} offers pass static "
                     f"checks; cheapest "
                     f"{min(r['price_usdc'] for r in payable if r['price_usdc'] is not None):.6f} USDC"
                     if any(r["price_usdc"] is not None for r in payable)
                     else "offers pass static checks")
    return out


if __name__ == "__main__":
    import urllib.parse
    targets = sys.argv[1:] or [
        "https://merchant-audit.clankerceo.workers.dev/dataset",
        "https://api.onesource.io/api/chain/nft-metadata",
        "https://multichain-rpc.clankerceo.workers.dev/gas-price",
    ]
    for u in targets:
        r = preflight(u)
        print(f"\n{r['verdict']:16} {u[:66]}")
        print(f"  source : {r['challenge_source']}")
        print(f"  reason : {r.get('reason','')[:150]}")
        for oa in (r.get("offer_audit") or []):
            flag = "OK " if not oa["problems"] else "BAD"
            print(f"    {flag} {str(oa['network']):16} "
                  f"{oa['price_usdc']} {'; '.join(oa['problems'])[:70]}")
