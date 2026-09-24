# Strict ISRO evaluator report — AegisBrowse v1.0 demo build

## Decision

**The supplied integration is now a coherent, runnable final demo baseline.** It
has a valid Chrome MV3 package, a usable popup, a local planner, an evaluator-safe
synthetic portal, guarded execution, and automated core/server tests.

It is **not yet evidence for the final learned-vision claims**. A national-level
submission must still bundle and evaluate the real trained ONNX detector and
measure browser resources on target devices.

## Defect closure

| Prior defect | v1.0 result |
|---|---|
| `coldStartInfo`/perception return-contract mismatch | Corrected; one telemetry contract |
| Missing `AEGIS_PROBE` | Corrected; role, label, origin, visibility and enabled state checked |
| Origin defaulted to safe | Corrected; provenance is locally resolved and unresolved/cross-origin targets fail closed |
| Missing ONNX assets crashed module graph | Corrected; resolvable local placeholder plus safe DOM fallback |
| ROI retained every actionable control | Corrected; goal relevance is mandatory |
| Full-page metadata survived a visual crop | Corrected; selected element IDs control semantic disclosure |
| Raw PII in user goal crossed network | Corrected; local typed-token substitution |
| MV3 confirmation was volatile and tab-ambiguous | Corrected; session storage, token, tab, origin and TTL binding |
| Repeated script injection added listeners | Corrected; installation guard is idempotent |
| Malformed Base64 crashed server | Corrected; strict validation with 422 response |
| Raw goals entered server logs | Corrected; only a short hash is logged |
| `PHOTO`/`IMAGE_REGION` vocabulary mismatch | Corrected; `IMAGE_REGION_n` used consistently |
| WAIT/STOP/SELECT/TYPE paths incomplete | Corrected; explicit handlers and confirmation for TYPE |
| React-style fields could reject direct `.value` | Corrected; native setters plus input/change events and verification |
| Download demo reported false failure | Corrected; Chrome Downloads event is a verification signal |
| Payload metric counted only Base64 characters | Corrected; PNG, Base64, metadata and serialized request bytes are separate |
| Redaction was invisible in the demo | Corrected; consent-gated three-stage Privacy Inspector |
| No independent evidence of server input | Corrected; server receipt renders the exact accepted crop and metadata |
| Server root returned Not Found | Corrected; root redirects to the demo portal |

## Reproduced test evidence

- Manifest parses as MV3 and every static import resolves.
- All extension JavaScript passes `node --check`.
- Python server and smoke test compile.
- Seventeen core assertions pass, including the negative case that Print and Help
  are not disclosed for the certificate-download task.
- `/health` returns success.
- The rules planner selects only `Download Certificate`.
- Malformed Base64 returns HTTP 422.
- The certificate route returns a downloadable attachment.

## Claims allowed today

- Working local DOM/structured privacy filter.
- Local redaction of recognized text values, secret inputs, and DOM-declared
  image regions.
- Goal-relevant visual crop and semantic-element minimization.
- Sanitized-goal and sanitized-page request boundary.
- Deterministic local planner integration, action gate, stale-target validation,
  durable confirmation and download-aware verification.

## Claims not allowed yet

- Trained in-browser visual detector performance.
- Browser OCR.
- Face-specific detection.
- WebGPU/WASM latency or memory numbers.
- Final visual-context accuracy on held-out pages.
- Improvement of the reported full-cascade redaction precision beyond 55.9%,
  unless a new benchmark run proves it.

## Submission verdict

**Use v1.0 for the working architecture/demo review. Do not present it as the
completed M1 learned-vision submission.** The next high-value milestone is to
train/export the actual detector, bundle real ONNX Runtime Web assets, and run
the published held-out benchmark plus Chrome resource measurements.
