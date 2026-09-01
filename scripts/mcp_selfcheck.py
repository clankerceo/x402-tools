"""Would an MCP reputation scanner grade my server well?

/mcp is now my single most-requested path (10 hits from independent crawlers,
including exaforce-mcprep "MCP server reputation scanner" and ProofBench "MCP
registry health probe"). These scanners are deciding whether my server is
listed and trusted. Test what they plausibly check.
"""
import json
import urllib.error
import urllib.request

URL = "https://multichain-rpc.clankerceo.workers.dev/mcp"
UA = {"user-agent": "clankerceo-selfcheck/1.0",
      "content-type": "application/json"}


def rpc(method, params=None, mid=1):
    body = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        body["params"] = params
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(URL, data=json.dumps(body).encode(),
                                   headers=UA), timeout=30)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:200]
    except Exception as e:
        return 0, str(e)[:150]


checks = []


def check(name, ok, detail=""):
    checks.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail[:80]}")


s, d = rpc("initialize", {"protocolVersion": "2024-11-05",
                          "capabilities": {},
                          "clientInfo": {"name": "scanner", "version": "1"}})
check("initialize returns result", s == 200 and "result" in d,
      f"status={s}")
if isinstance(d, dict) and "result" in d:
    r = d["result"]
    check("declares protocolVersion", bool(r.get("protocolVersion")),
          str(r.get("protocolVersion")))
    check("declares serverInfo.name",
          bool((r.get("serverInfo") or {}).get("name")),
          str((r.get("serverInfo") or {}).get("name")))
    check("declares capabilities", "capabilities" in r)

s, d = rpc("tools/list", mid=2)
tools = ((d or {}).get("result") or {}).get("tools") or []
check("tools/list returns tools", bool(tools), f"{len(tools)} tools")
if tools:
    check("every tool has description",
          all(t.get("description") for t in tools))
    check("every tool has inputSchema",
          all(isinstance(t.get("inputSchema"), dict) for t in tools))
    check("schemas declare type:object",
          all(t["inputSchema"].get("type") == "object" for t in tools))

# Error handling: scanners probe for graceful failure.
s, d = rpc("nonexistent/method", mid=3)
check("unknown method -> JSON-RPC error",
      isinstance(d, dict) and "error" in d, f"status={s}")

s, d = rpc("tools/call", {"name": "does_not_exist", "arguments": {}}, mid=4)
ok = isinstance(d, dict) and ("result" in d or "error" in d)
check("bad tool name handled gracefully", ok)

s, d = rpc("tools/call", {"name": "x402_check_endpoint", "arguments": {}},
           mid=5)
ok = isinstance(d, dict) and "result" in d
check("missing required arg handled", ok)

s, d = rpc("tools/call",
           {"name": "x402_gas_price", "arguments": {"chain": "base"}}, mid=6)
txt = ""
if isinstance(d, dict):
    c = ((d.get("result") or {}).get("content") or [{}])[0]
    txt = c.get("text") or ""
check("real tool call returns data", "gas_price_gwei" in txt or "block" in txt,
      txt[:60])

passed = sum(1 for _, ok, _ in checks if ok)
print(f"\n{passed}/{len(checks)} checks passed")
