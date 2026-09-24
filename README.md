# AegisBrowse — NEXORA final demo build v1.1

Problem statement **SIH26171: On-device Visual Perception for Light-weight Browser Agents**.

This package contains a runnable Chrome Manifest V3 extension, a local FastAPI
planner, and a synthetic scholarship portal that proves the primary path:

`capture → local PII/image-region redaction → goal-relevant crop → sanitized request → guarded click → verified download`

## What is in this package

| Folder | Contents |
|---|---|
| `aegisbrowse_extension/` | Chrome MV3 extension — DOM extractor, privacy layers, ROI selector, action gate, verifier |
| `aegisbrowse_server/` | FastAPI planner (rules backend runs with no model; open-weight VLM adapter available) |
| `nexora_benchmark/` | Generators, runtime, scorer and stored results that **reproduce the slide-4 preliminary validation figures** |
| `deck/` | The six-slide submission deck (PPTX + PDF) |
| `tests/`, `verify_package.sh` | Structure, import-graph, core-logic and server smoke checks |
| `docs/` | Evaluator report and video recording guide |

## Five-minute Windows demo

1. Open `aegisbrowse_server`, double-click `run_windows.bat`, and leave the
   terminal open. The script installs the three pinned Python packages and
   starts the server on `127.0.0.1:8000`.
2. In Chrome, open `chrome://extensions`, enable **Developer mode**, choose
   **Load unpacked**, and select the `aegisbrowse_extension` folder.
3. Click the AegisBrowse toolbar icon and choose **Open demo portal**.
4. On the demo page, open the extension again. Keep the default task:
   **Download my scholarship certificate**.
5. Enable **Video evidence mode**, then click **Run one safe step**. The extension locally redacts the applicant
   name, PAN, Aadhaar, email, phone, and image region; sends only the sanitized
   task crop plus controls inside that crop; clicks the same-origin Download
   Certificate control; and reports `download_started: true` in the trace.
6. Click **View privacy proof** to show Raw (local only) → Locally sanitized →
   Sent to planner. Click **Server receipt** to show the exact image and metadata
   accepted by `/plan`.

The planner endpoint is deliberately restricted to
`http://127.0.0.1:8000/plan` or its `localhost` equivalent in this prototype.

## What was corrected

- loadable MV3 manifest, popup, permissions and local-only planner endpoint;
- optional ONNX module/model use is lazy, so missing M1 assets no longer crash
  the service worker or prevent the DOM-safe demo from running;
- consistent perception telemetry (`cold_start`, preprocessing, inference,
  decode, provider) and honest JS-heap measurement notes;
- screenshot-pixel/CSS-pixel mapping;
- idempotent content-script injection and a real `AEGIS_PROBE` handler;
- locally derived link/form origin provenance (unknown/cross-origin is blocked);
- goal matching is required for ROI inclusion—unrelated Print, Help, and Log
  out controls are not disclosed merely because they are actionable;
- metadata is filtered to the selected visual crop and rebased afterward;
- PII in the user's natural-language goal is replaced with typed tokens before
  the network request;
- sensitivity uses overlap, not exact rectangle equality;
- durable confirmation state in `chrome.storage.session`, bound to tab, origin,
  target, token and expiry;
- WAIT, STOP, SCROLL, CLICK, TYPE and SELECT have explicit execution paths;
- framework-compatible input/select setters and post-write checks;
- stale-target role/label/origin/visibility/enabled revalidation;
- download-aware verification plus navigation, DOM, title and scroll signals;
- strict Base64/PNG validation, request limits, bounded confidence, restricted
  CORS and no raw-goal server logs;
- consistent `IMAGE_REGION_n` token vocabulary and actual request byte counts.
- consent-gated Privacy Inspector with three visual stages; compressed evidence
  stays in session storage and expires after ten minutes;
- server receipt page generated from the actual last planner request;
- the server root now redirects to the demo rather than returning Not Found.

## Verification

Install the verification and benchmark dependencies in an isolated environment:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Linux/macOS or Git Bash:

```bash
./verify_package.sh
```

The verifier checks the manifest and every static module dependency, parses all
Python/JavaScript, runs core privacy/ROI tests, launches the server, and tests
health, planning, the server receipt, malformed Base64 rejection, and the download endpoint.
It also confirms the benchmark harness imports and that its stored results match
the figures reported on slide 4.

To reproduce the slide-4 numbers from scratch:

```bash
cd nexora_benchmark
python3 make_portals.py --dev 12 --test 48
python3 evaluate_vision.py --dir pages_v2
```

See `nexora_benchmark/README.md` for the dev/held-out family split and the
honest reading of each metric (notably: these are P/R/F1 at IoU >= 0.5, **not**
mAP, and the detector is classical CV, not a learned model).

## Honest implementation boundary

The supplied build is a **working DOM + local privacy baseline**. DOM-visible
PII and DOM-declared image regions are sanitized locally and the complete demo
works without a learned model. A trained `ui_detector.onnx`, ONNX Runtime Web
browser assets, browser OCR, and a face-specific detector are **not fabricated
or claimed as complete**. Add the real held-out-trained assets using the READMEs
inside `aegisbrowse_extension/models` and `src/ort` before reporting learned
visual-context accuracy, WebGPU/WASM latency, face detection, or OCR results.

This distinction matters to an ISRO evaluator: the prototype can be run today,
while the highest-weight learned-vision milestone remains measurable future
work rather than a fake placeholder.
