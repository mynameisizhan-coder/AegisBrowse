#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scorer + layer ablation. The ONLY module that opens *.gt.json.

    python3 evaluate_vision.py --dir pages_v2

Reports, on the HELD-OUT test families only:
  UI detection      P / R / F1 at IoU >= 0.5, mean matched IoU   (NOT mAP)
  PII detection     P / R / F1  (content-inferred entities)
  Secret fields     P / R       (DOM-declared password/OTP, scored separately
                                 because they are trivially detectable)
  Redaction         pixel precision / recall / F1
                      recall    = sensitive pixels covered  (privacy)
                      precision = sensitive share of all masked pixels
                                  (utility; punishes over-masking)
  Latency           median and p95 over repeated runs after warm-up
"""
import argparse, glob, json, os, statistics, time
from collections import defaultdict
import numpy as np
from runtime import run, _iou

UI_CLASSES = {"button", "input", "image_region", "status_block", "value_chip"}
SECRETS = {"PASSWORD", "OTP"}


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def score_ui(dets, gt):
    gold = [g for g in gt if g["cls"] in UI_CLASSES]
    preds = sorted([d for d in dets if d["cls"] in UI_CLASSES], key=lambda d: -d["score"])
    matched, tp, fp, ious = set(), 0, 0, []
    for p in preds:
        best, bi = 0.0, -1
        for i, g in enumerate(gold):
            if i in matched or g["cls"] != p["cls"]:
                continue
            v = _iou(p["box"], g["box"])
            if v > best:
                best, bi = v, i
        if best >= 0.5:
            matched.add(bi); tp += 1; ious.append(best)
        else:
            fp += 1
    return tp, fp, len(gold) - len(matched), ious


def score_entities(plan, gt, want_secret):
    if want_secret:
        gold = [dict(g, key=g["secret"]) for g in gt if g.get("secret")]
        preds = [p for p in plan if p["cls"] in SECRETS]
    else:
        gold = [dict(g, key=g["pii"]) for g in gt if g.get("pii")]
        preds = [p for p in plan if p["cls"] not in SECRETS]
    matched, tp, fp = set(), 0, 0
    per = defaultdict(lambda: [0, 0, 0])
    for p in preds:
        best, bi = 0.0, -1
        for i, g in enumerate(gold):
            if i in matched or g["key"] != p["cls"]:
                continue
            v = _iou(p["box"], g["box"])
            if v > best:
                best, bi = v, i
        if best >= 0.5:
            matched.add(bi); tp += 1; per[p["cls"]][0] += 1
        else:
            fp += 1; per[p["cls"]][1] += 1
    for i, g in enumerate(gold):
        if i not in matched:
            per[g["key"]][2] += 1
    return tp, fp, len(gold) - len(matched), per


def redaction_pixels(plan, gt, W, H):
    sens = np.zeros((H, W), np.uint8)
    for g in gt:
        if g.get("pii") or g.get("secret"):
            b = g["box"]; sens[b[1]:b[3], b[0]:b[2]] = 1
    mask = np.zeros((H, W), np.uint8)
    for p in plan:
        b = [max(0, int(v)) for v in p["box"]]
        mask[b[1]:b[3], b[0]:b[2]] = 1
    return int((sens & mask).sum()), int(mask.sum()), int(sens.sum())


def timed(stem, dom, layers, use_ocr, narrow, reps, warm):
    for _ in range(warm):
        run(stem + ".png", dom, layers=layers, use_ocr=use_ocr, narrow=narrow)
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        run(stem + ".png", dom, layers=layers, use_ocr=use_ocr, narrow=narrow)
        ts.append((time.perf_counter() - t0) * 1000)
    return ts


def evaluate(pages, layers, use_ocr=True, narrow=True, reps=0, warm=0, lat_pages=5):
    U = [0, 0, 0]; ious = []
    P = [0, 0, 0]; pper = defaultdict(lambda: [0, 0, 0])
    S = [0, 0, 0]
    ri = rm = rs = 0
    lat = []
    for stem in pages:
        dom = json.load(open(stem + ".dom.json"))
        gt = json.load(open(stem + ".gt.json"))["elements"]
        dets, plan = run(stem + ".png", dom, layers=layers, use_ocr=use_ocr, narrow=narrow)
        a, b, c, iu = score_ui(dets, gt)
        U[0] += a; U[1] += b; U[2] += c; ious += iu
        a, b, c, per = score_entities(plan, gt, False)
        P[0] += a; P[1] += b; P[2] += c
        for k, v in per.items():
            for i in range(3):
                pper[k][i] += v[i]
        a, b, c, _ = score_entities(plan, gt, True)
        S[0] += a; S[1] += b; S[2] += c
        i_, m_, s_ = redaction_pixels(plan, gt, 1280, 720)
        ri += i_; rm += m_; rs += s_
    if reps:
        for stem in pages[:lat_pages]:
            dom = json.load(open(stem + ".dom.json"))
            lat += timed(stem, dom, layers, use_ocr, narrow, reps, warm)
    up, ur, uf = prf(*U)
    pp, prc, pf = prf(*P)
    sp, sr, sf = prf(*S)
    rprec = ri / rm if rm else 0.0
    rrec = ri / rs if rs else 0.0
    rf1 = 2 * rprec * rrec / (rprec + rrec) if rprec + rrec else 0.0
    return dict(
        ui=dict(precision=up, recall=ur, f1=uf,
                mean_iou=float(np.mean(ious)) if ious else 0.0),
        pii=dict(precision=pp, recall=prc, f1=pf,
                 per_class={k: dict(recall=v[0] / (v[0] + v[2]) if v[0] + v[2] else 0.0,
                                    precision=v[0] / (v[0] + v[1]) if v[0] + v[1] else 0.0)
                            for k, v in pper.items()}),
        secret=dict(precision=sp, recall=sr, f1=sf),
        redaction=dict(precision=rprec, recall=rrec, f1=rf1, leakage=1.0 - rrec),
        latency=(dict(median=statistics.median(lat),
                      p95=sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], n=len(lat))
                 if lat else None),
        pages=len(pages))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="pages_v2")
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--warm", type=int, default=3)
    a = ap.parse_args()
    dev = sorted(s[:-4] for s in glob.glob(os.path.join(a.dir, "dev_*.png")))
    test = sorted(s[:-4] for s in glob.glob(os.path.join(a.dir, "test_*.png")))
    fams = sorted({json.load(open(s + ".gt.json"))["family"] for s in test})
    print(f"development : {len(dev)} pages (tuning only)")
    print(f"HELD-OUT    : {len(test)} pages, families {fams}\n")

    cfgs = [("L1  structured (DOM+regex+checksum)", ("L1",), False, False, 15),
            ("L1+L2  + contextual heuristics", ("L1", "L2"), False, False, 15),
            ("L1+L2+L3  + visual/OCR reference", ("L1", "L2", "L3"), True, False, 3),
            ("L1+L2+L3  + span-level narrowing", ("L1", "L2", "L3"), True, True, 3)]
    out = {}
    hdr = (f"{'PIPELINE':<34}{'PII P':>7}{'PII R':>7}{'PII F1':>8}{'ADDR R':>8}"
           f"{'RedP':>7}{'RedR':>7}{'med ms':>8}")
    print(hdr); print("-" * len(hdr))
    for name, layers, ocr, narrow, reps in cfgs:
        r = evaluate(test, layers, use_ocr=ocr, narrow=narrow, reps=reps, warm=a.warm)
        out[name] = r
        pc = r["pii"]["per_class"]
        print(f"{name:<34}{r['pii']['precision']:>7.3f}{r['pii']['recall']:>7.3f}"
              f"{r['pii']['f1']:>8.3f}"
              f"{pc.get('ADDRESS', {}).get('recall', 0):>8.3f}"
              f"{r['redaction']['precision']:>7.3f}{r['redaction']['recall']:>7.3f}"
              f"{(r['latency']['median'] if r['latency'] else 0):>8.0f}")
    full = out[cfgs[-1][0]]
    print("-" * len(hdr))
    print(f"UI detection  : P {full['ui']['precision']:.3f}  R {full['ui']['recall']:.3f}  "
          f"F1 {full['ui']['f1']:.3f}  mean matched IoU {full['ui']['mean_iou']:.3f}")
    print(f"PII (full)    : P {full['pii']['precision']:.3f}  R {full['pii']['recall']:.3f}  "
          f"F1 {full['pii']['f1']:.3f}   micro-averaged over all classes")
    worst = sorted(full['pii']['per_class'].items(), key=lambda kv: kv[1]['recall'])[:3]
    print("                weakest classes by recall: " +
          ", ".join(f"{k} {v['recall']:.2f}" for k, v in worst))
    print(f"Secret fields : P {full['secret']['precision']:.3f}  R {full['secret']['recall']:.3f}  "
          f"(DOM-declared password/OTP, scored separately)")
    if full["latency"]:
        print(f"Latency       : median {full['latency']['median']:.0f} ms  "
              f"p95 {full['latency']['p95']:.0f} ms  (n={full['latency']['n']}, after warm-up)")
    print("\nnote: UI figures are P/R/F1 at IoU>=0.5, not mAP.")
    json.dump({"held_out_pages": len(test), "dev_pages": len(dev),
               "held_out_families": fams, "ablation": out},
              open("vision_results.json", "w"), indent=2)
    print("wrote vision_results.json")


if __name__ == "__main__":
    main()
