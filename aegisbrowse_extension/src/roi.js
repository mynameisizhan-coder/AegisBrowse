/**
 * Task-Aware Sanitized Context.
 *
 * Until now this was a slide claim: the client redacted the screen and then
 * shipped the WHOLE sanitized bitmap. This module makes it real. It scores
 * every region against the user's goal and emits the smallest crop that still
 * contains what the planner needs.
 *
 * Deliberately deterministic. No second model: relevance comes from goal-term
 * overlap, actionability, detector agreement and a sensitivity penalty, which
 * is auditable and cheap. A learned selector is only worth considering after
 * this baseline is measured.
 *
 *   R_i = a*U_i + b*G_i + c*C_i - d*S_i
 *
 *   U_i  goal relevance   (term overlap with label / text)
 *   G_i  actionability    (button, link, textbox, combobox)
 *   C_i  perception confidence for the region
 *   S_i  sensitivity cost (region is redacted / holds a secret)
 */

import { iou, coveredBy } from "./coords.js";

const W_GOAL = 1.2, W_ACT = 0.25, W_CONF = 0.2, W_SENS = 0.8;
const STOP = new Set(["the", "a", "an", "my", "our", "for", "to", "of", "in", "on",
  "and", "or", "please", "can", "you", "i", "me", "with", "from", "this", "that"]);

const terms = (s) =>
  (s || "").toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 2 && !STOP.has(t));

function goalScore(goalTerms, text) {
  if (!goalTerms.length) return 0;
  const t = terms(text);
  if (!t.length) return 0;
  let hits = 0;
  for (const g of goalTerms) if (t.some((x) => x === g || x.startsWith(g) || g.startsWith(x))) hits++;
  return hits / goalTerms.length;
}

const ACTIONABLE = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio"]);

/**
 * @param goal      user's natural-language goal
 * @param elements  DOM elements, rects already in SCREENSHOT space
 * @param detections perception output, screenshot space
 * @param plan      redaction plan, screenshot space
 * @param size      { width, height } of the screenshot
 */
export function selectContext(goal, elements, detections, plan, size) {
  const gt = terms(goal);
  const scored = elements.map((el) => {
    const U = goalScore(gt, `${el.label} ${el.text}`);
    const G = ACTIONABLE.has(el.role) ? 1 : 0;
    const det = detections.find((d) => iou(d.box, el.rect) > 0.4);
    const C = det ? det.score : 0;
    const S = plan.some((p) => coveredBy(el.rect, p.box) > 0.5) ? 1 : 0;
    return { el, score: W_GOAL * U + W_ACT * G + W_CONF * C - W_SENS * S, U, G, C, S };
  });

  // Actionability alone must never disclose every control on the page. A
  // region enters the task crop only when it matches the goal and is safe.
  const direct = scored.filter((s) => s.U > 0 && s.S === 0);
  if (!direct.length) {
    return {
      crop: [0, 0, 1, 1],
      mode: "minimal-empty",
      reason: "no safe goal-relevant region; disclose no page controls",
      kept: 0, considered: scored.length,
      pixel_fraction: +(1 / Math.max(1, size.width * size.height)).toFixed(6),
      selected_ids: [],
    };
  }

  // Add only nearby, non-sensitive text context around a matched control.
  const keep = [...direct];
  for (const candidate of scored) {
    if (candidate.S || candidate.G || candidate.U > 0) continue;
    const nearby = direct.some((target) => {
      const a = target.el.rect, b = candidate.el.rect;
      const verticalGap = Math.max(0, Math.max(a[1], b[1]) - Math.min(a[3], b[3]));
      const horizontalOverlap = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
      return verticalGap <= 120 && horizontalOverlap > 0;
    });
    if (nearby) keep.push(candidate);
  }

  const PAD = 24;
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const s of keep) {
    x1 = Math.min(x1, s.el.rect[0]); y1 = Math.min(y1, s.el.rect[1]);
    x2 = Math.max(x2, s.el.rect[2]); y2 = Math.max(y2, s.el.rect[3]);
  }
  const crop = [
    Math.max(0, Math.round(x1 - PAD)), Math.max(0, Math.round(y1 - PAD)),
    Math.min(size.width, Math.round(x2 + PAD)), Math.min(size.height, Math.round(y2 + PAD)),
  ];
  const cropArea = (crop[2] - crop[0]) * (crop[3] - crop[1]);
  const fullArea = size.width * size.height;
  // a crop that saves almost nothing is not worth the extra failure mode
  if (cropArea > 0.88 * fullArea) {
    return {
      crop: [0, 0, size.width, size.height], mode: "full-view",
      reason: "goal-relevant regions span the viewport",
      kept: keep.length, considered: scored.length,
      selected_ids: keep.map((s) => s.el.snapshot_id),
      pixel_fraction: 1,
    };
  }
  return {
    crop, mode: "task-roi",
    reason: `${keep.length} goal-relevant regions`,
    kept: keep.length, considered: scored.length,
    selected_ids: keep.map((s) => s.el.snapshot_id),
    pixel_fraction: +(cropArea / fullArea).toFixed(3),
    top: keep.sort((a, b) => b.score - a.score).slice(0, 5)
      .map((s) => ({ label: (s.el.label || s.el.text).slice(0, 40), score: +s.score.toFixed(2) })),
  };
}

/** Crop a bitmap and rebase rects into the crop's coordinate space. */
export async function applyCrop(bitmap, crop) {
  const [x1, y1, x2, y2] = crop;
  const w = x2 - x1, h = y2 - y1;
  const cv = new OffscreenCanvas(w, h);
  cv.getContext("2d").drawImage(bitmap, x1, y1, w, h, 0, 0, w, h);
  return {
    bitmap: cv.transferToImageBitmap(),
    rebase: ([a, b, c, d]) => [a - x1, b - y1, c - x1, d - y1],
  };
}
