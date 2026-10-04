# Selective escalation — measured results (2026-10-04)

All numbers below were produced on one machine by the scripts in this folder.
Nothing is estimated. Machine: Intel Core Ultra 9 275HX (24 cores), 31 GB RAM,
Windows 11, Python 3.10, OpenCV 4.12, Tesseract 5.4. CPU only.

## What changed

Error analysis showed **all** over-masking came from one rule: the visual
`image_region → PHOTO` detector. On unseen card layouts it labels the whole
content card (≈596×228 px, full of text) as a photo and blurs it — 68
predictions for 41 real photos, precision 0.41. Every other detector was at
pixel precision 1.00. (The dev families use a different layout, so this
failure never appeared during tuning.)

`runtime.run(..., selective=True)` adds:

1. **Structural photo signal** — `<img>`/`<canvas>` whose accessible label names a
   person photo is masked from the DOM (`layer_dom_images`).
2. **Container rejection** — a visual image region that contains other detected
   UI elements is a container, not a photo.
3. **OCR only where the DOM is blind** — a value chip is OCR'd only if no DOM
   element with text explains it.

No threshold was fitted to any dataset. The original always-on pipeline is
unchanged and still reproduces the original 48-page baseline exactly
(`vision_results.json`). The submission deck's slide 4 shows the fresh-set
rows below.

Because the failure was diagnosed on `pages_v2` held-out pages, the fix was
validated on **`pages_v3`, a fresh held-out corpus (seed base 50000) that was
never inspected**, plus a **DOM-blind stress variant** where every `<img>` and
~1/3 of value fields are removed from the DOM (as if rendered into canvas).

## Results (48 held-out pages each, families health/municipal/banking/transport)

| Set | Pipeline | PII P | PII R | Redaction P | Redaction R | OCR calls/page | Non-sensitive screen hidden | Median / p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| pages_v2 (slide-4 set) | Always-on vision + OCR | 0.912 | 0.962 | 0.559 | 0.984 | 3.8 | 7.19% | 306 / 455 |
| | **Selective** | **1.000** | **0.968** | **1.000** | 0.979 | **0.0** | **0.00%** | **17 / 21** |
| pages_v3 (fresh, never inspected) | Always-on vision + OCR | 0.937 | 0.955 | 0.643 | 0.977 | 3.4 | 4.95% | 261 / 461 |
| | **Selective** | **1.000** | **0.958** | **1.000** | 0.973 | **0.0** | **0.00%** | **12 / 20** |
| pages_v3 DOM-blind stress | Always-on vision + OCR | 0.929 | 0.833 | 0.627 | 0.911 | 3.4 | 4.95% | 260 / 442 |
| | **Selective** | **0.996** | 0.833 | **0.999** | 0.878 | **1.3** | **0.01%** | **49 / 299** |
| | Structural only | 1.000 | 0.580 | 1.000 | 0.556 | 0 | 0.00% | 6 / 6 |

UI detection (unchanged classical-CV detector): F1 0.937 (pages_v2), 0.924 (pages_v3) at IoU ≥ 0.5.

**Honest reading of the DOM-blind row.** Always-on's higher redaction recall
(0.911 vs 0.878) is accidental: its false "photo" blur over the whole card hides
10 names and 2 IFSC codes it never identified. Entity-level PII recall is
identical (0.833). The real weakness is OCR-only PII without a DOM label
(PERSON, IFSC) — the next thing to fix.

## Agent loop against the real planner server (`evaluate_loop.py`)

Pipeline → apply redaction to pixels → drop masked elements from metadata →
POST to `/plan` (rules backend) → check the action targets the page's
"Download …" control.

| Set | Pipeline | Planning success | PII strings in metadata | Request size | Local sanitize | Planner round-trip | Total median / p95 |
|---|---|---:|---:|---:|---:|---:|---:|
| pages_v3 | Selective | 48/48 | 0 | 69.5 KB | 22 ms | 19 ms | **47 / 48 ms** |
| pages_v3 | Always-on | 48/48 | 0 | 71.9 KB | 317 ms | 20 ms | 339 / 467 ms |
| DOM-blind | Selective | 48/48 | 0 | 71.3 KB | 94 ms | 20 ms | 120 / 270 ms |
| DOM-blind | Always-on | 48/48 | 0 | 76.4 KB | 315 ms | 20 ms | 342 / 469 ms |

The planner is the rules backend; an open-weight VLM planner was **not** measured.
Planning success is necessary but not sufficient for task success: the click is
not executed in this harness. In-browser execution and verification timing come
from the extension's own trace.

## Client resources (`resource_probe.py`, Python process)

| Set | Pipeline | Peak working set | CPU / page | Wall / page | OCR calls / page |
|---|---|---:|---:|---:|---:|
| pages_v3 | Selective | 56.4 MB | 25.7 ms | 15.4 ms | 0.00 |
| pages_v3 | Always-on | 57.3 MB | 52.1 ms | 261.0 ms | 3.42 |
| DOM-blind | Selective | 58.1 MB | 38.1 ms | 110.1 ms | 1.29 |
| DOM-blind | Always-on | 57.6 MB | 48.5 ms | 265.7 ms | 3.42 |

Baseline process RSS is ~35 MB. No learned model weights are used (classical
CV detector, 0 MB); the Tesseract English model is 3.9 MB. The extension's own
code is 68 KB. Tesseract child-process memory is not included.

**Not yet measured:** a trained ONNX detector, in-browser WebGPU/WASM inference,
browser JS heap, and in-browser end-to-end task time.

## Reproduce

```bash
python make_portals.py --dev 12 --test 48                                  # pages_v2
python make_portals.py --dev 0 --test 48 --out pages_v3 --seed-base 50000   # fresh set
python make_domblind.py --src pages_v3 --out pages_v3_domblind
python evaluate_selective.py --dir pages_v2 --dir pages_v3 --dir pages_v3_domblind
# start ../aegisbrowse_server (uvicorn app:app --port 8000), then:
python evaluate_loop.py --dir pages_v3 --selective 1
python resource_probe.py --dir pages_v3 --selective 1
```
