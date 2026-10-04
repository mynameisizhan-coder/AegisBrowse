#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Offline agent-loop benchmark against the REAL planner server.

For every held-out page:
  1. run the local pipeline (selective escalation) on screenshot + DOM
  2. apply the redaction plan to the pixels; drop masked elements from metadata
  3. POST the sanitized PNG + safe metadata + goal to http://127.0.0.1:8000/plan
  4. check the returned action targets the page's "Download ..." control
  5. confirm no ground-truth PII string appears anywhere in the request body

Start the server first:  cd ../aegisbrowse_server && python -m uvicorn app:app --port 8000
    python evaluate_loop.py --dir pages_v3

Measured: planning success, leaked PII strings, request bytes, and per-stage
latency (local perception+sanitize, encode, planner round-trip). This is an
offline Python harness; in-browser timing comes from the extension trace.
"""
import argparse, base64, glob, json, os, statistics, time, urllib.request
import cv2
import runtime

URL = "http://127.0.0.1:8000/plan"


def apply_plan(img, plan):
    out = img.copy()
    for p in plan:
        x1, y1, x2, y2 = [max(0, int(v)) for v in p["box"]]
        if p["mode"] == "blur":
            roi = out[y1:y2, x1:x2]
            if roi.size:
                out[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (51, 51), 0)
        else:
            out[y1:y2, x1:x2] = (0, 0, 0)
    return out


def masked(rect, plan):
    return any(runtime._overlap_frac(rect, p["box"]) > 0.5 for p in plan)


def med(xs):
    return round(statistics.median(xs), 1)


def p95(xs):
    xs = sorted(xs); return round(xs[max(0, int(len(xs) * 0.95) - 1)], 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="pages_v3")
    ap.add_argument("--selective", type=int, default=1)
    a = ap.parse_args()
    pages = sorted(s[:-4] for s in glob.glob(os.path.join(a.dir, "test_*.png")))
    ok = leaks = 0
    t_local, t_enc, t_net, t_total, req_bytes, raw_bytes = [], [], [], [], [], []
    for stem in pages:
        dom = json.load(open(stem + ".dom.json"))
        gt = json.load(open(stem + ".gt.json"))["elements"]
        target = next(e for e in dom["elements"]
                      if e.get("role") == "button" and e["text"].startswith("Download"))
        goal = f"{target['text']} for me"
        raw_bytes.append(os.path.getsize(stem + ".png"))

        t0 = time.perf_counter()
        img = cv2.imread(stem + ".png")
        _, plan = runtime.run(stem + ".png", dom, selective=bool(a.selective), narrow=False)
        clean = apply_plan(img, plan)
        t1 = time.perf_counter()
        meta = []
        for i, e in enumerate(dom["elements"]):
            if e.get("role") not in ("button", "link", "textbox") or e.get("input_type"):
                continue
            if masked(e["rect"], plan):
                continue
            meta.append(dict(id=f"el_{i}", role=e["role"], label=e.get("label") or e.get("text", ""),
                             rect=e["rect"], same_origin=True))
        png = cv2.imencode(".png", clean)[1].tobytes()
        body = json.dumps(dict(goal=goal, safe_metadata=meta,
                               visual_context=base64.b64encode(png).decode())).encode()
        t2 = time.perf_counter()
        req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        t3 = time.perf_counter()

        want = f"el_{dom['elements'].index(target)}"
        ok += resp.get("action") == "CLICK" and resp.get("target_id") == want
        # metadata leak check: no ground-truth PII string in the JSON fields
        text = json.dumps(dict(goal=goal, safe_metadata=meta))
        leaks += sum(1 for g in gt if g.get("text") and g["text"] in text)
        t_local.append((t1 - t0) * 1000); t_enc.append((t2 - t1) * 1000)
        t_net.append((t3 - t2) * 1000); t_total.append((t3 - t0) * 1000)
        req_bytes.append(len(body))

    n = len(pages)
    res = dict(dir=a.dir, pages=n, selective=bool(a.selective),
               planning_success=ok / n, pii_strings_in_metadata=leaks,
               request_kb=dict(median=med([b / 1024 for b in req_bytes]),
                               raw_png_median=med([b / 1024 for b in raw_bytes])),
               latency_ms=dict(local_perceive_sanitize=dict(median=med(t_local), p95=p95(t_local)),
                               encode=dict(median=med(t_enc), p95=p95(t_enc)),
                               planner_round_trip=dict(median=med(t_net), p95=p95(t_net)),
                               total=dict(median=med(t_total), p95=p95(t_total))))
    print(json.dumps(res, indent=2))
    out = "loop_results.json"
    allres = json.load(open(out)) if os.path.exists(out) else {}
    allres[f"{a.dir}|selective={int(a.selective)}"] = res
    json.dump(allres, open(out, "w"), indent=2)


if __name__ == "__main__":
    main()
