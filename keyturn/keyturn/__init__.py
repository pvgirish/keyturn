"""KeyTurn: completion checks for a planned database credential handover, for IBM Bob."""
import hashlib
import os

__version__ = "0.2.1"


def source_digest():
    """Short sha256 over this package's .py files (name + bytes, sorted). Identifies the exact code revision
    in proofs, done-checks and handover records; the same value is printed by the test reports."""
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for f in sorted(os.listdir(here)):
        if f.endswith(".py"):
            with open(os.path.join(here, f), "rb") as fh:
                h.update(f.encode() + b"\0" + fh.read())
    return h.hexdigest()[:16]


def revision():
    return {"keyturn_version": __version__, "keyturn_digest": source_digest()}
