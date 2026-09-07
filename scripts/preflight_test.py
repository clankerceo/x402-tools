"""Falsification tests for preflight — does it actually CATCH bad offers?

Every target I tried returned LOOKS_PAYABLE. That is the same "suspiciously
clean result" shape that produced five wrong conclusions earlier this week, so
before trusting the tool I feed it offers that MUST fail. If a deliberately
poisoned offer passes, the checker is decorative.

Each case names the single defect it injects.
"""
import sys

sys.path.insert(0, "/home/hexatron/ceo/gh/scripts")
from preflight import audit_offer  # noqa: E402

BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
GOOD_EVM = "0xCa03Fb4b1D2f66f5a83A5cA91021b874ac4a34a3"
SOL_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_NET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
GOOD_SOL = "CTmExzd1k8DNcmmuWGVCGoxsBshNcwFFhCe65QG57Vhd"


def offer(**kw):
    base = {"network": "eip155:8453", "asset": BASE_USDC,
            "payTo": GOOD_EVM, "maxAmountRequired": "1000"}
    base.update(kw)
    return base


CASES = [
    # (label, offer, must_fail?)
    ("clean Base offer", offer(), False),
    ("clean Solana offer",
     offer(network=SOL_NET, asset=SOL_MINT, payTo=GOOD_SOL), False),
    ("burn-address payTo",
     offer(payTo="0x000000000000000000000000000000000000dEaD"), True),
    ("zero-address payTo",
     offer(payTo="0x0000000000000000000000000000000000000000"), True),
    ("wrong asset (not USDC)",
     offer(asset="0xdAC17F958D2ee523a2206206994597C13D831ec7"), True),
    ("unknown network",
     offer(network="eip155:99999"), True),
    ("truncated EVM address",
     offer(payTo="0xCa03Fb4b1D2f66f5a83A5cA91021b874ac4a34"), True),
    ("EVM address on Solana network",
     offer(network=SOL_NET, asset=SOL_MINT, payTo=GOOD_EVM), True),
    ("Solana mint case-mangled",
     offer(network=SOL_NET, asset=SOL_MINT.lower(), payTo=GOOD_SOL), True),
    ("zero price", offer(maxAmountRequired="0"), True),
    ("negative price", offer(maxAmountRequired="-500"), True),
    ("absurd price (999 USDC)",
     offer(maxAmountRequired="999000000"), True),
    ("non-numeric price",
     offer(maxAmountRequired="lots"), True),
    ("missing payTo", offer(payTo=""), True),
    ("price in `amount` key only",
     {"network": "eip155:8453", "asset": BASE_USDC, "payTo": GOOD_EVM,
      "amount": "2000000"}, False),
]

passed = failed = 0
for label, o, must_fail in CASES:
    problems = audit_offer(o)
    caught = bool(problems)
    ok = (caught == must_fail)
    passed += ok
    failed += (not ok)
    verdict = "PASS" if ok else "**MISS**"
    detail = ("; ".join(problems)[:64] if problems else "no problems found")
    print(f"  {verdict:8} {label:34} {detail}")

print(f"\n{passed}/{len(CASES)} falsification tests behaved correctly")
if failed:
    print(f"{failed} FAILURES — the checker is not trustworthy yet")
    sys.exit(1)
print("The checker catches every injected defect and passes every clean offer.")
