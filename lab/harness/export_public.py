#!/usr/bin/env python3
"""Make a redacted copy of a run for sharing (judges/page). Raw run files stay private.
Masks: lab passwords, their md5 forms, and values of secret-looking settings.
Usage: export_public.py <run_dir> <old_pw> <new_pw> <pgb_admin_pw>"""
import hashlib, json, os, re, shutil, sys
RD, OLD, NEW, ADM = sys.argv[1:5]
PUB = os.path.join(RD, "public"); os.makedirs(PUB, exist_ok=True)
secrets_lit = [OLD, NEW, ADM, "super-Pa55-2026"]
for pw, user in ((OLD, "mastodon"), (NEW, "mastodon"), (ADM, "pgbouncer")):
    secrets_lit.append(hashlib.md5((pw + user).encode()).hexdigest())
KEYS = re.compile(r"^([+\- ]?\s*[A-Z0-9_]*(SECRET|KEY|PASS|OTP|VAPID|SALT|TOKEN)[A-Z0-9_]*\s*=\s*)(.*)$", re.M)
def redact(text):
    for s in secrets_lit:
        text = text.replace(s, "[REDACTED]")
    text = KEYS.sub(lambda m: m.group(1) + "[REDACTED]", text)
    text = re.sub(r"password=\S+", "password=[REDACTED]", text)
    text = re.sub(r'"md5[0-9a-f]{32}"', '"md5[REDACTED]"', text)
    text = re.sub(r"(Bearer |access_token=)[A-Za-z0-9_\-]+", r"\1[REDACTED]", text)
    return text
files = ["summary.txt", "summary.json", "probes-before.jsonl", "probes-post-reconnect.jsonl", "probes-post-restart.jsonl",
         "interventions.jsonl", "migrate.json", "marker.json", "marker-result.json", "images.txt", "host.txt",
         "phase0/phase0.json", "phaseA/phaseA.json", "phaseB/phaseB.json", "phaseA/raw/workspace.diff", "monitor.jsonl"]
for rel in files:
    src = os.path.join(RD, rel)
    if not os.path.exists(src):
        continue
    dst = os.path.join(PUB, rel.replace("/", "__"))
    open(dst, "w").write(redact(open(src, errors="replace").read()))
print("redacted copy in", PUB)
