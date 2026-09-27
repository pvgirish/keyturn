"""Customer journeys on the Mastodon test stack (synthetic accounts only).
One journey = Alice posts (web) -> the post reaches Bob's home timeline (needs sidekiq)
-> Bob's streaming connection authenticates (streaming). /health is recorded separately,
because it can stay 200 while customers fail."""
import datetime
import json
import time
import urllib.error
import urllib.request

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _tokens(cfg):
    return dict(l.strip().split("=", 1) for l in open(cfg["tokens_file"]) if "=" in l)


def _req(cfg, url, token, data=None, timeout=10):
    h = {"Host": cfg["host_header"], "X-Forwarded-Proto": "https", "Authorization": "Bearer " + token}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=h, method="POST" if data is not None else "GET")
    try:
        with _opener.open(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()


def journey(cfg, label):
    tok = _tokens(cfg)
    A, B = tok["ALICE_TOKEN"], tok["BOB_TOKEN"]
    t0 = time.time()
    out = {"t": datetime.datetime.utcnow().strftime("%H:%M:%S"), "label": label}
    s, b = _req(cfg, cfg["web_url"] + "/api/v1/statuses", A, {"status": "keyturn %s %.0f" % (label, t0), "visibility": "public"})
    out["post"] = s
    sid = None
    if s == 200:
        try:
            sid = json.loads(b).get("id")
        except Exception:
            sid = None
    seen = False
    if sid:
        for _ in range(15):
            s2, b2 = _req(cfg, cfg["web_url"] + "/api/v1/timelines/home?limit=5", B)
            try:
                if s2 == 200 and any(x.get("id") == sid for x in json.loads(b2)):
                    seen = True
                    break
            except Exception:
                pass
            time.sleep(1)
    out["timeline"] = "ok" if seen else ("n/a" if not sid else "missing")
    try:
        r = urllib.request.Request(cfg["stream_url"] + "/api/v1/streaming/user?access_token=" + B,
                                   headers={"Host": cfg["host_header"], "X-Forwarded-Proto": "https"})
        with _opener.open(r, timeout=5) as resp:
            out["stream"] = resp.status
    except urllib.error.HTTPError as e:
        out["stream"] = e.code
    except Exception as e:
        out["stream"] = "timeout" if "timed out" in str(e) else str(e)[:40]
    s3, _ = _req(cfg, cfg["web_url"] + "/health", A)
    out["health"] = s3
    out["ok"] = out["post"] == 200 and out["timeline"] == "ok" and out["stream"] == 200
    return out


def journeys(cfg, label, n=3, gap=3.0):
    res = []
    for i in range(n):
        res.append(journey(cfg, "%s-%d" % (label, i + 1)))
        if i < n - 1:
            time.sleep(gap)
    return res


def health(cfg):
    try:
        r = urllib.request.Request(cfg["web_url"] + "/health", headers={"Host": cfg["host_header"], "X-Forwarded-Proto": "https"})
        with _opener.open(r, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def wait_health(cfg, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if health(cfg) == 200:
            return True
        time.sleep(3)
    return False
