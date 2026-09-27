#!/usr/bin/env python3
"""P2a customer-action probe for the Mastodon + PgBouncer test stack.
Each probe = one customer journey: Alice posts (web), Bob sees it on his home timeline
(needs sidekiq), Bob's streaming connection authenticates (streaming). Writes JSON lines.
Usage: harness.py <label> [count] [gap_seconds]"""
import json, os, sys, time, urllib.request, urllib.error, datetime

BASE = "http://localhost:3000"; STREAM = "http://localhost:4000"
HDR = {"Host": "mastodon.test", "X-Forwarded-Proto": "https"}
tok = dict(l.strip().split("=", 1) for l in open(os.path.join(os.path.dirname(__file__), "tokens.env")) if "=" in l)
A, B = tok["ALICE_TOKEN"], tok["BOB_TOKEN"]
os.environ.pop("http_proxy", None); os.environ.pop("HTTP_PROXY", None)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def req(url, token, data=None, timeout=10):
    h = dict(HDR, Authorization=f"Bearer {token}")
    body = None
    if data is not None:
        body = json.dumps(data).encode(); h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=h, method="POST" if data is not None else "GET")
    try:
        with opener.open(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()

def probe(label):
    t0 = time.time(); out = {"t": datetime.datetime.now().strftime("%H:%M:%S"), "label": label}
    s, b = req(f"{BASE}/api/v1/statuses", A, {"status": f"probe {label} {t0:.0f}", "visibility": "public"})
    out["post"] = s
    sid = json.loads(b).get("id") if s == 200 else None
    seen = False
    if sid:
        for _ in range(15):
            s2, b2 = req(f"{BASE}/api/v1/timelines/home?limit=5", B)
            if s2 == 200 and any(x.get("id") == sid for x in json.loads(b2)):
                seen = True; break
            time.sleep(1)
    out["timeline"] = "ok" if seen else ("n/a" if not sid else "missing")
    # streaming auth: 200 means Bob's token was checked against the database
    try:
        r = urllib.request.Request(f"{STREAM}/api/v1/streaming/user?access_token={B}", headers=HDR)
        with opener.open(r, timeout=5) as resp:
            out["stream"] = resp.status
    except urllib.error.HTTPError as e:
        out["stream"] = e.code
    except Exception as e:
        out["stream"] = "timeout" if "timed out" in str(e) else str(e)[:40]
    s3, _ = req(f"{BASE}/health", A)
    out["health"] = s3
    out["ok"] = out["post"] == 200 and out["timeline"] == "ok" and out["stream"] == 200
    return out

if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "probe"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    gap = float(sys.argv[3]) if len(sys.argv) > 3 else 10
    for i in range(n):
        o = probe(f"{label}-{i+1}")
        print(json.dumps(o), flush=True)
        if i < n - 1: time.sleep(gap)
