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
| `nexora_benchmark/` | Generators, runtime (always-on and **selective escalation**), scorers and stored results that **reproduce every figure in the deck** |
| `deck/` | The six-slide SIH submission deck (PDF to upload, PPTX source) |
| `tests/`, `verify_package.sh` | Structure, import-graph, core-logic and server smoke checks |

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

## Measured results

Selective escalation runs structural signals first and escalates to vision or
OCR only where the DOM is blind. Always-on vision blurred whole content cards as
if they were photos; selective escalation removes that over-masking. Fresh
held-out set (48 pages, 4 portal families never used for tuning, 408 annotated
sensitive items):

| Criterion (weight) · measure | Always-on | Selective |
|---|---:|---:|
| Visual context (25%) · UI F1 at IoU ≥ 0.5 | 0.924 | 0.924 |
| PII detection (20%) · precision / recall | 0.937 / 0.955 | **1.000 / 0.958** |
| Redaction (20%) · pixel precision / recall | 0.643 / 0.977 | **1.000 / 0.973** |
| Resources (20%) · Python RAM / CPU per page | 57.3 MB / 52.1 ms | **56.4 MB / 25.7 ms** |
| Latency (15%) · sanitize → plan, median / p95 | 339 / 467 ms | **47 / 48 ms** |
| Planner picks the right control | 48 / 48 | 48 / 48 |

On the original 48-page held-out set, redaction precision rises from 0.559 to
1.000 at recall 0.979. Measured on an Intel Core Ultra 9 275HX, CPU only, with
the rules planner. Full tables, the DOM-blind stress test and reproduction
commands: [`nexora_benchmark/SELECTIVE_RESULTS.md`](nexora_benchmark/SELECTIVE_RESULTS.md).

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

The script uses `python3`, falling back to `python` (on Windows `python3` is
often the Microsoft Store stub); set `PYTHON=/path/to/python` to override.

The verifier checks the manifest and every static module dependency, parses all
Python/JavaScript, runs core privacy/ROI tests, launches the server, and tests
health, planning, the server receipt, malformed Base64 rejection, and the download endpoint.
It also confirms the benchmark harness imports and that its stored results match
the figures in the deck: the original baseline, the selective-escalation results
and the agent-loop timings.

Regenerating the benchmark needs Tesseract OCR and wkhtmltopdf on `PATH`
(Debian/Ubuntu: `sudo apt install tesseract-ocr wkhtmltopdf`; Windows:
`winget install UB-Mannheim.TesseractOCR wkhtmltopdf.wkhtmltox`). To reproduce
the numbers from scratch:

```bash
cd nexora_benchmark
python make_portals.py --dev 12 --test 48                                  # pages_v2
python evaluate_vision.py --dir pages_v2                                   # original baseline
python make_portals.py --dev 0 --test 48 --out pages_v3 --seed-base 50000   # fresh held-out set
python make_domblind.py --src pages_v3 --out pages_v3_domblind
python evaluate_selective.py --dir pages_v2 --dir pages_v3 --dir pages_v3_domblind
```

Accuracy figures reproduce exactly; timings vary with the machine.

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

**Still not measured:** a trained ONNX detector, WebGPU timing in the browser,
and the time for a whole task to finish inside the browser. The visual layer and
selective escalation currently run in the Python benchmark, not yet inside the
extension.

This distinction matters to an ISRO evaluator: the prototype can be run today,
while the highest-weight learned-vision milestone remains measurable future
work rather than a fake placeholder.
