/**
 * Coordinate spaces.
 *
 * DOM rects come from getBoundingClientRect() and are in CSS pixels.
 * The screenshot from captureVisibleTab() is in device pixels. Under OS
 * scaling, browser zoom or a HiDPI display these differ, and assuming they
 * are equal is a PRIVACY bug, not a cosmetic one: a redaction rectangle
 * computed in CSS space lands in the wrong place on the bitmap and can leave
 * the value it was meant to cover fully visible.
 *
 * Everything downstream of `makeMapper` works in ONE space: screenshot pixels.
 */

export function makeMapper(dom, bitmap) {
  const sx = bitmap.width / dom.width;
  const sy = bitmap.height / dom.height;
  const exact = Math.abs(sx - 1) < 1e-3 && Math.abs(sy - 1) < 1e-3;
  return {
    sx, sy, exact,
    dpr: dom.dpr,
    /** CSS-pixel rect -> screenshot-pixel rect */
    toShot: ([x1, y1, x2, y2]) => [
      Math.round(x1 * sx), Math.round(y1 * sy),
      Math.round(x2 * sx), Math.round(y2 * sy),
    ],
    /** screenshot-pixel rect -> CSS-pixel rect (for executing clicks) */
    toCss: ([x1, y1, x2, y2]) => [
      Math.round(x1 / sx), Math.round(y1 / sy),
      Math.round(x2 / sx), Math.round(y2 / sy),
    ],
    describe: () => ({
      css_viewport: [dom.width, dom.height],
      screenshot: [bitmap.width, bitmap.height],
      scale: [+sx.toFixed(3), +sy.toFixed(3)],
      device_pixel_ratio: dom.dpr,
    }),
  };
}

/** Rect intersection-over-union, shared by the gate and the metadata builder. */
export function iou(a, b) {
  const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[2], b[2]), y2 = Math.min(a[3], b[3]);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter;
  return ua > 0 ? inter / ua : 0;
}

/** Fraction of `a` covered by `b` — better than IoU for "is this redacted?". */
export function coveredBy(a, b) {
  const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[2], b[2]), y2 = Math.min(a[3], b[3]);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const area = (a[2] - a[0]) * (a[3] - a[1]);
  return area > 0 ? inter / area : 0;
}
