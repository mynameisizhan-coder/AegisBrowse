# NEXORA benchmark & evaluation harness

Reproduces the **PRELIMINARY VALIDATION** figures on slide 4 of the submission
deck. Pure Python — no GPU, no browser, no trained model required.

```bash
pip install opencv-python numpy pillow      # tesseract-ocr also required for L3
sudo apt install tesseract-ocr wkhtmltopdf  # Debian/Ubuntu

python3 make_portals.py --dev 12 --test 48  # generate the synthetic corpus
python3 evaluate_vision.py --dir pages_v2   # score HELD-OUT pages only
```

`vision_results.json` in this folder is the output of that exact command, so the
slide-4 table can be checked without re-running anything.

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
Ground truth exists solely to score predictions *after* inference. An earlier
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

## Held-out results (48 pages, 4 unseen families)

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
| `runtime.py` | The runtime pipeline — L1 structural, L2 contextual, L3 visual/OCR |
| `evaluate_vision.py` | The only module that opens ground truth; scores UI, PII, secrets, redaction, latency |
| `make_panels.py` | Renders the raw → detected → redacted proof panels from predictions only |
| `generate_pages.py`, `detector.py`, `evaluate.py` | Text-only structured PII benchmark (60 pages) |
| `vision_results.json`, `results.json` | Stored outputs backing the deck |
