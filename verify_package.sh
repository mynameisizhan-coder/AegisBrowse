#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# python3 on Windows is often the Microsoft Store stub; fall back to python.
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in python3 python; do
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
      PY="$candidate"; break
    fi
  done
fi
[[ -n "$PY" ]] || { echo "No Python 3.9+ interpreter found (set PYTHON=...)"; exit 1; }

required=(
  aegisbrowse_extension/manifest.json
  aegisbrowse_extension/src/service_worker.js
  aegisbrowse_extension/src/content_dom.js
  aegisbrowse_extension/src/perception.js
  aegisbrowse_extension/src/privacy.js
  aegisbrowse_extension/src/coords.js
  aegisbrowse_extension/src/disclosure.js
  aegisbrowse_extension/src/roi.js
  aegisbrowse_extension/src/popup.html
  aegisbrowse_extension/src/popup.css
  aegisbrowse_extension/src/popup.js
  aegisbrowse_extension/src/proof.html
  aegisbrowse_extension/src/proof.css
  aegisbrowse_extension/src/proof.js
  aegisbrowse_server/app.py
  aegisbrowse_server/requirements.txt
  tests/test_core.mjs
  tests/smoke_server.py
)

for file in "${required[@]}"; do
  [[ -f "$file" ]] || { echo "MISSING: $file"; exit 1; }
done

"$PY" - <<'PY'
import json
from pathlib import Path

root = Path("aegisbrowse_extension")
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
assert manifest["manifest_version"] == 3
assert manifest["version"] == "1.1.0"
assert manifest["background"]["type"] == "module"
worker = root / manifest["background"]["service_worker"]
assert worker.is_file()

for js in root.rglob("*.js"):
    text = js.read_text(encoding="utf-8")
    for token in text.splitlines():
        token = token.strip()
        if token.startswith("import ") and ' from "' in token:
            rel = token.split(' from "', 1)[1].split('"', 1)[0]
            assert (js.parent / rel).resolve().is_file(), f"unresolved static import {rel} in {js}"
print("manifest/import graph: passed")
PY

for file in aegisbrowse_extension/src/*.js tests/test_core.mjs; do node --check "$file"; done
"$PY" -m py_compile aegisbrowse_server/app.py tests/smoke_server.py
node tests/test_core.mjs

if ! "$PY" -c 'import fastapi,uvicorn,pydantic' >/dev/null 2>&1; then
  echo "Python server packages are not installed. Run: $PY -m pip install -r requirements-dev.txt"
  exit 2
fi

"$PY" -m uvicorn app:app --app-dir aegisbrowse_server --host 127.0.0.1 --port 8000 >"${TMPDIR:-/tmp}/aegisbrowse_server.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in {1..30}; do
  "$PY" - <<'PY' >/dev/null 2>&1 && break || true
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=.3)
PY
  sleep .2
done
"$PY" tests/smoke_server.py

# benchmark harness: imports cleanly and its stored results match the deck
"$PY" - <<'PY'
import json, sys, inspect
sys.path.insert(0, "nexora_benchmark")
import runtime, detector  # noqa: F401  (import-only check)
assert "selective" in inspect.signature(runtime.run).parameters, "runtime.run lacks selective mode"

def close(label, got, want, tol=0.001):
    assert abs(got - want) < tol, f"{label}: stored {got:.3f} != expected {want:.3f}"

# original always-on baseline on pages_v2 (evaluate_vision.py output)
d = json.load(open("nexora_benchmark/vision_results.json", encoding="utf-8"))
assert d["held_out_pages"] == 48, f"expected 48 held-out pages, got {d['held_out_pages']}"
full = list(d["ablation"].values())[2]
close("baseline PII precision", full["pii"]["precision"], 0.918)
close("baseline PII recall", full["pii"]["recall"], 0.968)
close("baseline redaction recall", full["redaction"]["recall"], 0.984)
close("baseline redaction precision", full["redaction"]["precision"], 0.559)
close("baseline UI F1", full["ui"]["f1"], 0.937)

# deck slide 4: fresh held-out set pages_v3 (evaluate_selective.py output)
s = json.load(open("nexora_benchmark/selective_results.json", encoding="utf-8"))["pages_v3"]
assert s["pages"] == 48
always, sel = s["configs"]["Always-on vision + OCR"], s["configs"]["Selective escalation"]
for name, cfg, want in (("always-on", always, (0.924, 0.937, 0.955, 0.643, 0.977)),
                        ("selective", sel, (0.924, 1.000, 0.958, 1.000, 0.973))):
    close(f"{name} UI F1", cfg["ui"]["f1"], want[0])
    close(f"{name} PII precision", cfg["pii"]["precision"], want[1])
    close(f"{name} PII recall", cfg["pii"]["recall"], want[2])
    close(f"{name} redaction precision", cfg["redaction"]["precision"], want[3])
    close(f"{name} redaction recall", cfg["redaction"]["recall"], want[4])

# deck slides 4-5: sanitize-to-plan loop against the planner (evaluate_loop.py output)
loop = json.load(open("nexora_benchmark/loop_results.json", encoding="utf-8"))
for key, med in (("pages_v3|selective=1", 47), ("pages_v3|selective=0", 339)):
    r = loop[key]
    assert r["planning_success"] == 1.0 and r["pii_strings_in_metadata"] == 0, key
    assert round(r["latency_ms"]["total"]["median"]) == med, f"{key}: median {r['latency_ms']['total']['median']}"
print("benchmark: imports OK, stored results match the deck (baseline, selective, agent loop)")
PY

echo "PACKAGE + CORE RUNTIME CHECKS: PASS"
