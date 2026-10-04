# NEXORA benchmark & evaluation harness

Reproduces every measured figure in the submission deck. Pure Python — no GPU,
no browser, no trained model required.

```bash
pip install -r ../requirements-dev.txt      # numpy, opencv, Pillow, psutil
sudo apt install tesseract-ocr wkhtmltopdf  # Debian/Ubuntu
# Windows: winget install UB-Mannheim.TesseractOCR wkhtmltopdf.wkhtmltox

python make_portals.py --dev 12 --test 48   # generate the synthetic corpus
python evaluate_vision.py --dir pages_v2    # score HELD-OUT pages only
```

`vision_results.json` in this folder is the output of that exact command, so the
original baseline can be checked without re-running anything. The
selective-escalation results the deck reports are in
[`SELECTIVE_RESULTS.md`](SELECTIVE_RESULTS.md); see
[Selective escalation](#selective-escalation) below.

## The architectural rule this harness enforces

```
                 RUNTIME  (runtime.py)
screenshot ──────────────► detectors ──► PREDICTED boxes ──► redactor
DOM snapshot ────────────►

                 EVALUATION ONLY  (evaluate_vision.py)
PREDICTED boxes ─┐
                 ├──► scorer
ground truth ────┘
```

`runtime.py` reads only `*.png` and `*.dom.json`. It never opens a `*.gt.json`.
Ground truth exists solely to score predictions *after* inference; the scorers
(`evaluate_vision.py`, `evaluate_selective.py`, `evaluate_loop.py`) are the only
modules that open it. An earlier
revision violated this and produced a circular "0% leakage" result; the
separation is now enforced by module boundary.

## Split — family-level, not just page-level

|  | Families | Layout / theme |
|---|---|---|
| dev (12 pages) | scholarship, HR | single-column tables, light themes |
| **held-out (48 pages)** | **health, municipal, banking, transport** | **card + two-column, four unseen themes** |

Each family has its own field vocabulary and buttons — a health portal shows
Patient ID and *Download Report*, never Scholarship Status. Heuristics were
tuned on the dev families only.

## Original held-out results (48 pages, 4 unseen families)

| Pipeline | PII P | PII R | Redaction R | Redaction P | Median latency |
|---|---:|---:|---:|---:|---:|
| L1 structural (DOM + regex + checksum) | 100.0% | 68.5% | 63.2% | 100.0% | 8 ms |
| L1+L2 + contextual heuristics | 100.0% | 83.8% | 71.7% | 100.0% | 8 ms |
| L1+L2+L3 + visual / OCR reference | 91.8% | **96.8%** | **98.4%** | 55.9% | 417 ms |

UI element detection (full pipeline): **P 0.947 · R 0.928 · F1 0.937 at
IoU ≥ 0.5**, mean matched IoU 0.902.

Secret fields (DOM-declared password/OTP) score P/R 1.000 and are reported
**separately** — they are trivially detectable and would otherwise inflate the
PII numbers.

**The finding that matters:** visual escalation lifts redaction recall to 98.4%
but drops redaction precision to 55.9% — it over-masks. That measured trade-off
is the argument for selective rather than always-on escalation, and it is why
the architecture escalates on uncertainty and task need instead of every frame.

## Selective escalation

Error analysis traced **all** of the over-masking to one rule: on unseen card
layouts the visual `image_region → PHOTO` detector labelled the whole content
card as a photo and blurred it. `runtime.run(..., selective=True)`:

1. masks `<img>`/`<canvas>` elements whose label names a person photo, from the DOM;
2. rejects a visual image region that contains other UI elements — a container,
   not a photo;
3. runs OCR only on text the DOM does not explain (canvas, image-rendered text).

No threshold was fitted to any dataset, and the always-on path is unchanged.
Because the failure was found on `pages_v2`, the fix was validated on
`pages_v3`, a **fresh held-out set** (new seeds) that was never inspected, and on
`pages_v3_domblind`, where every `<img>` and about a third of value fields are
removed from the DOM.

| Set | Pipeline | PII P / R | Redaction P / R | Sanitize → plan median |
|---|---|---:|---:|---:|
| pages_v2 (original) | Selective | 1.000 / 0.968 | 1.000 / 0.979 | — |
| pages_v3 (fresh) | Always-on | 0.937 / 0.955 | 0.643 / 0.977 | 339 ms |
| pages_v3 (fresh) | **Selective** | **1.000 / 0.958** | **1.000 / 0.973** | **47 ms** |
| pages_v3 DOM-blind | Selective | 0.996 / 0.833 | 0.999 / 0.878 | 120 ms |

On DOM-blind pages always-on reaches 0.911 redaction recall only because its
whole-card blur happens to cover names it never identified; entity-level recall
is identical (0.833). Full tables, the agent-loop and resource measurements:
[`SELECTIVE_RESULTS.md`](SELECTIVE_RESULTS.md).

```bash
python make_portals.py --dev 0 --test 48 --out pages_v3 --seed-base 50000
python make_domblind.py --src pages_v3 --out pages_v3_domblind
python evaluate_selective.py --dir pages_v2 --dir pages_v3 --dir pages_v3_domblind
# with ../aegisbrowse_server running on port 8000:
python evaluate_loop.py --dir pages_v3 --selective 1
python resource_probe.py --dir pages_v3 --selective 1
```

## Reading these numbers honestly

- **Not mAP.** These are P/R/F1 at IoU ≥ 0.5. No confidence-ranked
  precision–recall curve is integrated, so calling it mAP would be wrong. True
  `mAP@0.5` and `mAP@0.5:0.95` arrive with the trained ONNX detector.
- **Classical CV, not a learned model.** `detect_ui()` is Canny → contours →
  geometry and ink statistics. Its `score` field is a heuristic rule score, not
  a learned confidence. It establishes the accuracy floor and fixes the
  ground-truth harness so the ONNX model can be dropped in and compared
  like-for-like.
- **L2 is heuristics, not NER.** Regex plus a stop-list. A learned NER model
  would be a separate, later claim.
- **`image_region` is not face detection.** The synthetic photograph is a grey
  placeholder, so this measures image-region localisation only.
- **Latency is offline CPU**, not in-browser.
- **0% leakage is never claimed as a system property** — only as a result on
  this 48-page held-out set.

## Files

| File | Purpose |
|---|---|
| `make_portals.py` | Generates the synthetic corpus: `.png` + `.dom.json` (runtime) + `.gt.json` (eval only) |
| `runtime.py` | The runtime pipeline — L1 structural, L2 contextual, L3 visual/OCR; `selective=True` for selective escalation |
| `evaluate_vision.py` | Scores the original ablation (UI, PII, secrets, redaction, latency) from ground truth |
| `evaluate_selective.py` | Always-on vs selective: adds OCR calls per page, over-masked screen share, task-control visibility |
| `evaluate_loop.py` | Sanitize → plan loop against the real `/plan` server: planning success, PII leak check, request size, latency |
| `resource_probe.py` | Peak memory and CPU time of the pipeline process |
| `make_domblind.py` | DOM-blind stress variant of a corpus (same screenshots and ground truth) |
| `make_panels.py` | Renders the raw → detected → redacted proof panels from predictions only |
| `generate_pages.py`, `detector.py`, `evaluate.py` | Text-only structured PII benchmark (60 pages) |
| `vision_results.json`, `results.json` | Stored outputs of the original baseline |
| `selective_results.json`, `loop_results.json` | Stored outputs backing the deck's slides 4 and 5 |
| `vision_results_windows_rerun.json` | Re-run of the original baseline on Windows (accuracy matches to within OCR-version noise) |
| `SELECTIVE_RESULTS.md` | Write-up of the selective-escalation results with reproduction commands |
