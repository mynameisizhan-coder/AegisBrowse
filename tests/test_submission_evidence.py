"""Check stored submission evidence, without claiming to rerun experiments."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "nexora_benchmark"
selective = json.loads((ROOT / "selective_results.json").read_text())
loop = json.loads((ROOT / "loop_results.json").read_text())
fresh = selective["pages_v3"]
assert fresh["pages"] == 48
assert set(fresh["families"]) == {"health", "municipal", "banking", "transport"}
current = fresh["configs"]["Selective escalation"]
for metric, key, expected in [
    ("ui", "f1", 0.924),
    ("pii", "precision", 1.000),
    ("pii", "recall", 0.958),
    ("redaction", "precision", 1.000),
    ("redaction", "recall", 0.973),
]:
    assert round(current[metric][key], 3) == expected, (metric, key)
stress = selective["pages_v3_domblind"]["configs"]["Selective escalation"]
assert round(stress["redaction"]["recall"], 3) == 0.878
planning = loop["pages_v3|selective=1"]
assert planning["pages"] == 48
assert planning["planning_success"] == 1.0
assert planning["pii_strings_in_metadata"] == 0
assert round(planning["latency_ms"]["total"]["median"]) == 47
assert round(planning["latency_ms"]["total"]["p95"]) == 48
print("submission evidence: stored accuracy/planning values agree with the deck")
