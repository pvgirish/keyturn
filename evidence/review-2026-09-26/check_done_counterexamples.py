"""Independent, offline review probes. Does not run Docker or modify product code."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "app/keyturn"))
from keyturn import hook_done

parts = ("proof1_customers_on_new", "proof2_old_refused", "proof3_exercised")
results = []
with tempfile.TemporaryDirectory(prefix="keyturn-review-") as tmp:
    cfg = {"state_dir": tmp}
    with patch.object(hook_done.obs, "fingerprint", return_value="review-state"), \
         patch.object(hook_done.obs, "sh", side_effect=AssertionError("No external commands permitted")):
        for name, all_pass, errors, expected in (
            ("valid_control", True, [], True),
            ("observation_error", False, ["synthetic observation unavailable"], False),
            ("aggregate_false", False, [], False),
        ):
            proof = {k: {"pass": True, "checks": []} for k in parts}
            proof.update(fingerprint="review-state", all_pass=all_pass, observation_errors=errors)
            Path(tmp, "proofs.json").write_text(json.dumps(proof))
            actual, reasons = hook_done.verdict(cfg)
            results.append({"case": name, "expected_verified": expected,
                            "actual_verified": actual, "matches_expected": actual == expected,
                            "reasons": reasons})

for message, expected in (("Not done; the live rotation is still pending.", False),
                          ("Rotation completed successfully.", True)):
    actual = bool(hook_done.DONE_WORDS.search(message))
    results.append({"case": "completion_language", "message": message,
                    "expected_claimed_done": expected, "actual_claimed_done": actual,
                    "matches_expected": actual == expected})

out = {
    "scope": "Isolated synthetic counterexamples against actual v0.1 hook; no live verdict or outage inference",
    "source": str(ROOT / "app/keyturn/keyturn/hook_done.py"),
    "source_sha256": hashlib.sha256((ROOT / "app/keyturn/keyturn/hook_done.py").read_bytes()).hexdigest(),
    "results": results,
}
dest = Path(__file__).with_name("done-counterexamples.json")
dest.write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
