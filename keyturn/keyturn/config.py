"""KeyTurn configuration.

Everything private (passwords, the inventory answer key, logs) lives in KEYTURN_HOME
(default ~/.keyturn), OUTSIDE the workspace Bob edits. Nothing here is ever printed.
Python 3.9+ standard library only.
"""
import json
import os

KEYTURN_HOME = os.path.expanduser(os.environ.get("KEYTURN_HOME", "~/.keyturn"))
CONFIG_PATH = os.path.join(KEYTURN_HOME, "keyturn.local.json")

DEFAULTS = {
    "database": "mastodon_production",
    "db_container": "db",
    "pgbouncer_container": "pgbouncer",
    "db_superuser": "postgres",
    "pgbouncer_host": "pgbouncer",
    "pgbouncer_port": "6432",
    "postgres_host": "db",
    "postgres_port": "5432",
    "apps": ["web", "sidekiq", "streaming"],
    "containers": ["db", "redis", "pgbouncer", "web", "sidekiq", "streaming"],
    "web_url": "http://localhost:3000",
    "stream_url": "http://localhost:4000",
    "host_header": "mastodon.test",
    "config_files": [".env.production", "pgbouncer/pgbouncer.ini", "pgbouncer/userlist.txt", "docker-compose.yml"],
}


class ConfigError(Exception):
    pass


def load(path=None):
    p = path or CONFIG_PATH
    if not os.path.exists(p):
        raise ConfigError("KeyTurn is not installed: %s is missing (run install.sh)" % p)
    cfg = dict(DEFAULTS)
    cfg.update(json.load(open(p)))
    for k in ("workspace", "old", "new", "pgbouncer_admin", "tokens_file"):
        if k not in cfg:
            raise ConfigError("config key missing: %s" % k)
    cfg["workspace"] = os.path.expanduser(cfg["workspace"])
    cfg.setdefault("state_dir", os.path.join(KEYTURN_HOME, "state"))
    cfg["state_dir"] = os.path.expanduser(cfg["state_dir"])
    cfg.setdefault("answer_key", os.path.join(KEYTURN_HOME, "answer-key.json"))
    cfg["answer_key"] = os.path.expanduser(cfg["answer_key"])
    os.makedirs(cfg["state_dir"], exist_ok=True)
    return cfg


def secret_values(cfg):
    """All secret strings that must never appear in any output."""
    vals = [cfg["old"].get("password"), cfg["new"].get("password"), cfg["pgbouncer_admin"].get("password")]
    return [v for v in vals if v]


def redact(obj, cfg):
    """Replace any secret value found in strings of a JSON-able object."""
    secrets = secret_values(cfg)
    labels = {cfg["old"].get("password"): "<old>", cfg["new"].get("password"): "<new>",
              cfg["pgbouncer_admin"].get("password"): "<admin>"}

    def fix(x):
        if isinstance(x, str):
            for s in secrets:
                if s and s in x:
                    x = x.replace(s, labels.get(s, "<secret>"))
            return x
        if isinstance(x, list):
            return [fix(i) for i in x]
        if isinstance(x, dict):
            return {k: fix(v) for k, v in x.items()}
        return x

    return fix(obj)
