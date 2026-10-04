#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Always-on vs selective escalation, on held-out pages only.

    python evaluate_selective.py --dir pages_v2 --dir pages_v3 --dir pages_v3_domblind

Adds three measurements to the evaluate_vision.py metrics:
  ocr/page        Tesseract calls per page (the expensive step)
  over-mask       non-sensitive pixels hidden, as % of the 1280x720 viewport
  task control    held-out pages whose "Download ..." button stays >=50% visible
                  (necessary for the planner to complete the task)
"""
import argparse, glob, json, os, statistics, time
import numpy as np
import runtime
from evaluate_vision import evaluate

W, H = 1280, 720
CFGS = [
    ("Structural only (L1+L2)", dict(layers=("L1", "L2"), use_ocr=False, narrow=False)),
    ("Always-on vision + OCR", dict(layers=("L1", "L2", "L3"), use_ocr=True, narrow=False)),
    ("Selective escalation", dict(layers=("L1", "L2", "L3"), use_ocr=True, narrow=False,
                                  selective=True)),
]


def extras(pages, kw):
    ocr = over = 0
    task_ok = task_n = 0
    for stem in pages:
        dom = json.load(open(stem + ".dom.json"))
        gt = json.load(open(stem + ".gt.json"))["elements"]
        before = runtime.STATS["ocr_calls"]
        _, plan = runtime.run(stem + ".png", dom, **kw)
        ocr += runtime.STATS["ocr_calls"] - before
        sens = np.zeros((H, W), np.uint8)
        for g in gt:
            if g.get("pii") or g.get("secret"):
                b = g["box"]; sens[b[1]:b[3], b[0]:b[2]] = 1
        mask = np.zeros((H, W), np.uint8)
        for p in plan:
            b = [max(0, int(v)) for v in p["box"]]
            mask[b[1]:b[3], b[0]:b[2]] = 1
        over += int((mask & (1 - sens)).sum())
        # the task target: the page's "Download ..." button, read from the
        # screenshot-aligned DOM of the ORIGINAL page (buttons are never removed)
        for el in dom["elements"]:
            if el.get("role") == "button" and el.get("text", "").startswith("Download"):
                b = el["rect"]; task_n += 1
                area = (b[2] - b[0]) * (b[3] - b[1])
                task_ok += mask[b[1]:b[3], b[0]:b[2]].sum() <= 0.5 * area
    n = len(pages)
    return dict(ocr_per_page=ocr / n, overmask_pct=100.0 * over / (n * W * H),
                task_control_visible=task_ok / task_n if task_n else 0.0)


def latency(pages, kw, reps=5, warm=1, k=8):
    ts = []
    for stem in pages[:k]:
        dom = json.load(open(stem + ".dom.json"))
        for i in range(warm + reps):
            t0 = time.perf_counter()
            runtime.run(stem + ".png", dom, **kw)
            if i >= warm:
                ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return dict(median=statistics.median(ts), p95=ts[max(0, int(len(ts) * 0.95) - 1)], n=len(ts))


def evaluate_kw(pages, kw):
    sel = kw.get("selective", False)
    if not sel:
        return evaluate(pages, kw["layers"], use_ocr=kw["use_ocr"], narrow=kw["narrow"])
    # evaluate() predates the selective flag; route it through a thin shim
    orig = runtime.run
    import evaluate_vision as ev
    ev.run = lambda png, dom, **k: orig(png, dom, selective=True, **k)
    try:
        return evaluate(pages, kw["layers"], use_ocr=kw["use_ocr"], narrow=kw["narrow"])
    finally:
        ev.run = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", required=True)
    ap.add_argument("--out", default="selective_results.json")
    a = ap.parse_args()
    out = {}
    for d in a.dir:
        test = sorted(s[:-4] for s in glob.glob(os.path.join(d, "test_*.png")))
        fams = sorted({json.load(open(s + ".gt.json"))["family"] for s in test})
        print(f"\n== {d}: {len(test)} held-out pages, families {fams}")
        hdr = (f"{'PIPELINE':<26}{'PII P':>7}{'PII R':>7}{'RedP':>7}{'RedR':>7}"
               f"{'UI F1':>7}{'ocr/pg':>8}{'over%':>7}{'task':>7}{'med ms':>8}{'p95':>6}")
        print(hdr); print("-" * len(hdr))
        out[d] = {"pages": len(test), "families": fams, "configs": {}}
        for name, kw in CFGS:
            r = evaluate_kw(test, kw)
            r.update(extras(test, kw))
            r["latency"] = latency(test, kw)
            out[d]["configs"][name] = r
            print(f"{name:<26}{r['pii']['precision']:>7.3f}{r['pii']['recall']:>7.3f}"
                  f"{r['redaction']['precision']:>7.3f}{r['redaction']['recall']:>7.3f}"
                  f"{r['ui']['f1']:>7.3f}{r['ocr_per_page']:>8.1f}{r['overmask_pct']:>7.2f}"
                  f"{r['task_control_visible']:>7.2f}{r['latency']['median']:>8.0f}"
                  f"{r['latency']['p95']:>6.0f}")
    json.dump(out, open(a.out, "w"), indent=2)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
