"""Verify the header-vs-body challenge finding before publishing it.

Claim: a meaningful share of x402 endpoints return an EMPTY body ({}) and put
the real challenge in the `payment-required` header. A census that parses the
body first silently discards those.

This must be measured precisely, not asserted, because I intend to publish it.
Classifies every candidate into: body-only, header-only, both, or neither.
"""
import base64
import json
import urllib.error
import urllib.request

UA = {"user-agent": "clankerceo/1.0", "accept": "application/json"}


def classify(url):
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                               timeout=18)
        return "no_402"
    except urllib.error.HTTPError as e:
        if e.code != 402:
            return f"http_{e.code}"
        raw = e.read().decode("utf-8", "replace")
        hdr = e.headers.get("payment-required")

        body_ok = False
        try:
            b = json.loads(raw)
            body_ok = bool(b.get("accepts"))
        except Exception:
            pass

        head_ok = False
        if hdr:
            try:
                h = json.loads(base64.b64decode(hdr + "=="))
                head_ok = bool(h.get("accepts"))
            except Exception:
                pass

        if body_ok and head_ok:
            return "both"
        if head_ok:
            return "header_only"
        if body_ok:
            return "body_only"
        return "neither"
    except Exception as e:
        return "unreachable"


urls = json.load(open("/home/hexatron/ceo/x402/candidates.json"))
from collections import Counter

counts = Counter()
header_only = []
for u in urls:
    c = classify(u)
    counts[c] += 1
    if c == "header_only":
        header_only.append(u)

total_402 = sum(v for k, v in counts.items()
                if k in ("both", "header_only", "body_only", "neither"))
print(f"sampled: {len(urls)}   endpoints returning 402: {total_402}\n")
for k, v in counts.most_common():
    print(f"  {k:14} {v}")

if total_402:
    ho = counts["header_only"]
    print(f"\nHEADER-ONLY: {ho}/{total_402} = {ho/total_402*100:.1f}% of "
          f"402-emitting endpoints")
    print("These are INVISIBLE to a body-first parser.\n")
    for u in header_only[:12]:
        print("   ", u[:88])
