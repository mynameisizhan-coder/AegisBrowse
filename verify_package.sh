#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

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

python3 - <<'PY'
import json
from pathlib import Path

root = Path("aegisbrowse_extension")
manifest = json.loads((root / "manifest.json").read_text())
assert manifest["manifest_version"] == 3
assert manifest["version"] == "1.1.0"
assert manifest["background"]["type"] == "module"
worker = root / manifest["background"]["service_worker"]
assert worker.is_file()

for js in root.rglob("*.js"):
    text = js.read_text()
    for token in text.splitlines():
        token = token.strip()
        if token.startswith("import ") and ' from "' in token:
            rel = token.split(' from "', 1)[1].split('"', 1)[0]
            assert (js.parent / rel).resolve().is_file(), f"unresolved static import {rel} in {js}"
print("manifest/import graph: passed")
PY

for file in aegisbrowse_extension/src/*.js tests/test_core.mjs; do node --check "$file"; done
python3 -m py_compile aegisbrowse_server/app.py tests/smoke_server.py
node tests/test_core.mjs

if ! python3 -c 'import fastapi,uvicorn,pydantic' >/dev/null 2>&1; then
  echo "Python server packages are not installed. Run: python3 -m pip install -r aegisbrowse_server/requirements.txt"
  exit 2
fi

python3 -m uvicorn app:app --app-dir aegisbrowse_server --host 127.0.0.1 --port 8000 >/tmp/aegisbrowse_server.log 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in {1..30}; do
  python3 - <<'PY' >/dev/null 2>&1 && break || true
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=.3)
PY
  sleep .2
done
python3 tests/smoke_server.py

# benchmark harness: imports cleanly and its stored results match the deck
python3 - <<'PY'
import json, sys, pathlib
sys.path.insert(0, "nexora_benchmark")
import runtime, detector  # noqa: F401  (import-only check)
d = json.load(open("nexora_benchmark/vision_results.json"))
assert d["held_out_pages"] == 48, f"expected 48 held-out pages, got {d['held_out_pages']}"
full = list(d["ablation"].values())[2]
for label, got, want in (
    ("PII precision", full["pii"]["precision"], 0.918),
    ("PII recall", full["pii"]["recall"], 0.968),
    ("redaction recall", full["redaction"]["recall"], 0.984),
    ("redaction precision", full["redaction"]["precision"], 0.559),
    ("UI F1", full["ui"]["f1"], 0.937),
):
    assert abs(got - want) < 0.001, f"{label}: stored {got:.3f} != deck {want:.3f}"
print("benchmark: imports OK, stored results match deck slide 4")
PY

echo "PACKAGE + CORE RUNTIME CHECKS: PASS"
