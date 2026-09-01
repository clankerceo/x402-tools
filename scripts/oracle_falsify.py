"""Is "CDP says isValid" actually evidence the MERCHANT is broken?

25/25 THEIR_BUG is the same shape as the four instrument failures I hit today,
so before believing it I need to know what CDP /verify is really asserting.

CDP verifies a signed EIP-3009 authorization: correct signature, sufficient
balance, sane validity window. It does NOT know the merchant's route price,
required params, or business rules. So isValid:true means "this payment is
cryptographically spendable", not "this merchant should have accepted it".

Falsification test: verify a payload for a payTo address that is NOT a merchant
at all (a random address, and my own). If CDP returns isValid:true for those
too, then isValid carries no information about the merchant and my 25/25 is
worthless as evidence.
"""
import os
import subprocess
import sys

CASES = [
    ("real merchant (base-gas)", "0x0D083590c048A243e24a75E3a7C968145DE25B44"),
    ("random non-merchant addr", "0x000000000000000000000000000000000000dEaD"),
    ("vitalik.eth (not a merchant)",
     "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"),
]

for label, addr in CASES:
    p = subprocess.run(
        [sys.executable, "/home/hexatron/ceo/x402/verify_mine.py"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "V_PAY_TO": addr, "V_AMOUNT": "1000"})
    out = ((p.stdout or "") + (p.stderr or "")).replace(" ", "").replace("\\", "")
    if '"isValid":true' in out:
        v = "isValid:TRUE"
    elif '"isValid":false' in out:
        v = "isValid:false"
    else:
        v = "unknown"
    print(f"  {v:14} {label}")

print("\nIf all three say TRUE, isValid says nothing about the merchant and")
print("'25/25 their bug' is NOT a finding.")
