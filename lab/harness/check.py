#!/usr/bin/env python3
"""P2a deterministic checker (no AI). Reports who is connected with which database user,
at Postgres and at PgBouncer, and whether given credentials are accepted.
Usage: check.py [label=user:password[@host:port]] ..."""
import json, subprocess, sys
ADM = "pgb-admin-2026"
def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)
def names():
    m = {}
    for n in ["db","redis","pgbouncer","web","sidekiq","streaming","migrate"]:
        r = sh(f"docker inspect -f '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {n} 2>/dev/null")
        if r.stdout.strip(): m[r.stdout.strip()] = n
    return m
def pg_sessions():
    r = sh("docker exec db psql -U postgres -Atc \"select usename, coalesce(host(client_addr),'local') , count(*) from pg_stat_activity where datname='mastodon_production' and usename<>'postgres' group by 1,2 order by 1\"")
    ip = names()
    return [f"{u} from {ip.get(a,a)} x{c}" for u,a,c in (l.split('|') for l in r.stdout.split() if l)]
def pgb(show):
    r = sh(f"docker exec -e PGPASSWORD={ADM} db psql -h pgbouncer -p 6432 -U pgbouncer pgbouncer -Atc 'SHOW {show}'")
    ip = names(); out = {}
    for l in r.stdout.splitlines():
        f = l.split('|')
        if len(f) > 5 and f[2] == 'mastodon_production':
            key = f"{f[1]} from {ip.get(f[5], f[5])}"
            out[key] = out.get(key, 0) + 1
    return [f"{k} x{v}" for k,v in sorted(out.items())] if r.returncode == 0 else [r.stderr.strip()[:120]]
def login(user, pw, host="db", port=5432):
    r = sh(f"docker exec -e PGPASSWORD='{pw}' db psql -h {host} -p {port} -U {user} -d mastodon_production -Atc 'select 1'")
    return "accepted" if r.returncode == 0 else "refused: " + r.stderr.strip().split('\n')[-1][:90]
if __name__ == "__main__":
    out = {"postgres_sessions": pg_sessions(), "pgbouncer_servers": pgb("SERVERS"), "pgbouncer_clients": pgb("CLIENTS")}
    for spec in sys.argv[1:]:          # label=user:password[@host:port]
        label, _, rest = spec.partition('=')
        cred, _, hp = rest.partition('@'); u, _, p = cred.partition(':')
        h, _, pt = (hp or "db:5432").partition(':')
        out[f"login {label} ({u}@{h}:{pt})"] = login(u, p, h, int(pt))
    print(json.dumps(out, indent=1))
