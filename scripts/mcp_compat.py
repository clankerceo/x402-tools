"""Would a real MCP client succeed against my server, end to end?

35 crawlers found me but nobody has called a tool for real. Before assuming
that is a demand problem, rule out a compatibility problem: my self-check
speaks my own dialect. Real clients (Claude, Cursor, mcp-remote) send specific
headers, expect specific session behaviour, and may use a newer protocol
version than I hardcoded.

Tests the things a real client does that my self-check does not.
"""
import json
import urllib.error
import urllib.request

URL = "https://multichain-rpc.clankerceo.workers.dev/mcp"


def call(body, headers=None, label=""):
    h = {"content-type": "application/json",
         "user-agent": "clankerceo-compat/1.0"}
    h.update(headers or {})
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(URL, data=json.dumps(body).encode(),
                                   headers=h), timeout=30)
        raw = r.read().decode("utf-8", "replace")
        return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, {}, str(e)[:200]


checks = []


def rec(name, ok, detail=""):
    checks.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail[:90]}")


# 1. Clients send Accept: application/json, text/event-stream (streamable-http)
s, h, b = call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18",
                           "capabilities": {},
                           "clientInfo": {"name": "claude", "version": "1"}}},
               {"accept": "application/json, text/event-stream"})
rec("accepts SSE-style Accept header", s == 200, f"status={s}")

# 2. Newer protocol version — must not hard-fail
ok = False
try:
    d = json.loads(b)
    ok = "result" in d
    ver = (d.get("result") or {}).get("protocolVersion")
except Exception:
    ver = None
rec("handles newer protocolVersion (2025-06-18)", ok, f"echoed={ver}")

# 3. Some clients expect an Mcp-Session-Id they can reuse
sid = h.get("Mcp-Session-Id") or h.get("mcp-session-id")
rec("session id header present (optional)", True,
    f"{'present: ' + sid[:16] if sid else 'absent (stateless — fine)'}")

# 4. notifications/initialized must not error
s2, _, b2 = call({"jsonrpc": "2.0", "method": "notifications/initialized"})
rec("notifications/initialized accepted", s2 in (200, 202, 204),
    f"status={s2}")

# 5. Batch request (JSON-RPC 2.0 allows arrays)
s3, _, b3 = call([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
rec("batch array handled (or cleanly refused)", s3 in (200, 400, 404),
    f"status={s3} {b3[:60]}")

# 6. CORS preflight — browser-based clients need this
try:
    # Explicit UA: Cloudflare 403s Python's default `Python-urllib/3.x`
    # before the Worker runs, which would make this measure the harness.
    r = urllib.request.urlopen(urllib.request.Request(
        URL, method="OPTIONS",
        headers={"origin": "https://example.com",
                 "access-control-request-method": "POST",
                 "user-agent": "clankerceo-compat/1.0"}), timeout=20)
    acao = r.headers.get("access-control-allow-origin")
    rec("CORS preflight OK", bool(acao), f"ACAO={acao}")
except Exception as e:
    rec("CORS preflight OK", False, str(e)[:70])

# 7. GET should not 405 (some clients probe it / SSE)
try:
    r = urllib.request.urlopen(urllib.request.Request(
        URL, headers={"accept": "text/event-stream",
                      "user-agent": "clankerceo-compat/1.0"}), timeout=20)
    rec("GET probe returns something useful", r.status == 200,
        f"status={r.status}")
except urllib.error.HTTPError as e:
    rec("GET probe returns something useful", False, f"status={e.code}")

print(f"\n{sum(checks)}/{len(checks)} compatibility checks passed")
