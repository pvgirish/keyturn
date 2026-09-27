"""KeyTurn transition watch: while a credential change is in progress, sample one customer journey and the
stored-password fingerprints about every 5 seconds. Writes state/watch.jsonl. Stops on state/watch.stop or
after 45 minutes. What it records is observation, not a guarantee: gaps between samples are not seen."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from keyturn import checker  # noqa: E402
from keyturn import config as C  # noqa: E402
from keyturn import obs  # noqa: E402
from keyturn import probe  # noqa: E402

PERIOD = float(os.environ.get("KEYTURN_WATCH_PERIOD", "5"))
MAX_S = float(os.environ.get("KEYTURN_WATCH_MAX", str(45 * 60)))
RUN = os.environ.get("KEYTURN_WATCH_RUN")


def main():
    cfg = C.load()
    stop = os.path.join(cfg["state_dir"], "watch.stop")
    t0 = time.time()
    i = 0
    time.sleep(PERIOD)
    def superseded():
        try:
            return (checker.read_json(cfg, "watch-run.json") or {}).get("id") != RUN
        except Exception:
            return False
    while not os.path.exists(stop) and time.time() - t0 < MAX_S and not superseded():
        i += 1
        start = time.time()
        try:
            rows, _ = obs.roles(cfg)
            checker.record_verifiers(cfg, rows, obs.db_now(cfg))
        except Exception:
            pass
        try:
            j = probe.journey(cfg, "watch-%d" % i)
            rec = {"at": obs.utcnow(), "ok": bool(j.get("ok")), "post": j.get("post"), "timeline": j.get("timeline"),
                   "stream": j.get("stream"), "health": j.get("health")}
        except Exception as e:
            rec = {"at": obs.utcnow(), "ok": False, "error": str(e)[:120]}
        rec["run"] = RUN
        checker.append(cfg, "watch.jsonl", C.redact(rec, cfg))
        time.sleep(max(0.5, PERIOD - (time.time() - start)))
    if not os.path.exists(stop) and not superseded():  # ended by the time limit, not by watch action=stop
        try:
            run = checker.read_json(cfg, "watch-run.json") or {}
            if run.get("id") == RUN and not run.get("stopped_at"):
                run.update(stopped_at=obs.utcnow(), ended="time limit reached")
                checker.write_json(cfg, "watch-run.json", run)
        except Exception:
            pass
    try:
        pidf = os.path.join(cfg["state_dir"], "watch.pid")
        if open(pidf).read().strip() == str(os.getpid()):
            os.remove(pidf)
    except Exception:
        pass


if __name__ == "__main__":
    main()
