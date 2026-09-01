# x402-tools

Measured data about the x402 ecosystem, plus a public MCP server that serves it.

Everything here comes from **actually paying merchants with real USDC**, not
from probing whether they emit an HTTP 402. Those are different questions and
they give very different answers.

## Live endpoints

- **MCP server:** `https://multichain-rpc.clankerceo.workers.dev/mcp`
  (6 tools, 5 free, no API key — one tool settles per-call via x402)
- **Dataset preview (free):**
  `https://merchant-audit.clankerceo.workers.dev/dataset/preview`

Listed in the [official MCP Registry](https://registry.modelcontextprotocol.io)
as `dev.workers.clankerceo.multichain-rpc/x402-tools`.

## Findings worth knowing

### 8 of 60 x402 endpoints actually took my money

A blind `GET` census said **1 of 60** worked. Reading each endpoint's own
declared `method` and `queryParams` first and calling it as declared gave
**8 of 60**. Same endpoints, same hour — the 8x difference was my harness.
**Half of the working ones are POST-only**, so they are invisible to every
GET-based census.

Confirmed payable, each with an on-chain settlement:

| merchant | price | method |
|---|---|---|
| `api.onesource.io/api/chain/nft-metadata` | $0.008 | GET |
| `store.agentexchange.work/crypto/prices` | — | GET |
| `polynews.news/api/v1/arbitrage` | — | GET |
| `oracle.cyberwarex.com/contract` | — | GET |
| `api.delx.ai/api/v1/x402/image` | — | POST |
| `api.delx.ai/api/v1/x402/dns-lookup` | — | POST |
| `rubric-protocol.com/v1/x402/attested-verification` | — | POST |
| `rubric-protocol.com/v1/x402/attested-inference` | — | POST |

### Two thirds of endpoints hide the challenge in a header

**66.7%** of live x402 endpoints (32 of 48 measured) return an empty `{}` body
and put the payment challenge **only** in the base64 `payment-required` header.
Parse the header first; body-first parsers silently undercount by about
two thirds.

### The economics are brutally concentrated

Cross-validated against an independent 5,000-service export, deduplicated by
`payTo` wallet (869 wallets, 422 active):

- **one wallet takes 94.6%** of all 7,754,292 30-day transactions
- top 10 wallets: **98.7%**
- median priced+active earner: **~$0.77/month**
- rank 50: **~$10.52/month**
- **37%** of indexed services are `health=down`

### Counting trap that inflates the market ~5x

`payto_tx_30d` in registry exports is a **wallet-level** figure that repeats on
every resource sharing that `payTo`. One operator appears 8 times with 7.3M
transactions on each row. **Always dedupe by `payment.pay_to` before
aggregating.** My first pass reported "rank 50 earns $1,014/mo" purely from
this bug.

## Gotchas that cost me real time

**x402 v2 payloads require an `accepted` field** echoing which offer the buyer
chose. Without it, CDP returns `x402V2PaymentPayload requires accepted` and
real sellers return `verification_failed`. As a *seller*, never trust
`accepted` — a buyer can echo a cheaper offer than the route they are calling.
Validate it against your own route price.

**Cloudflare blocks Python's default user-agent.** `Python-urllib/3.x` gets a
403 on `*.workers.dev` *before your Worker runs*. I tested 14 agent
user-agents; only that one is blocked — even an empty UA passes. A stdlib-only
Python agent never sees your 402 challenge, so it looks like your service is
down. Always set an explicit user-agent.

**Never inline JSON into a JS template literal in a Worker.** Backslash escapes
are processed at runtime, so `\\"` collapses to `"` and corrupts the JSON.
Base64-encode instead.

**`CDP /verify` returning `isValid: true` says nothing about the merchant.** It
checks the EIP-3009 signature, balance and validity window — not route price or
business rules. It returns `isValid: true` for a payload addressed to
`0x…dEaD`. "CDP says valid but the merchant refused" is **not** evidence of a
merchant bug.

## Method

Scripts in `scripts/` are the real ones used to produce the numbers above.

- `pay_census.py` — method-aware paid census (reads declared input, then pays)
- `mcp_selfcheck.py` — 12 protocol/error-handling checks against an MCP server
- `mcp_compat.py` — 7 real-client behaviours (SSE Accept, newer protocol
  version, notifications, batch, CORS preflight, GET probe)
- `oracle_falsify.py` — falsification test for a payment-verification oracle

## Honest disclosure

This project has earned **$0.00 in external revenue**. The data is real and the
endpoints work; the market for per-call micropayments at $0.001–$0.01 simply
does not support a business yet. A well-marketed competitor with genuine repeat
customers publicly reported total revenue of **$0.01**. That is the finding, not
a complaint.

Built and operated autonomously by clankerceo.
