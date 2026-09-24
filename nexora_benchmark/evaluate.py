#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXORA benchmark scorer.
Produces the numbers for the 20% PII-detection and 20% redaction criteria.

Run:  python3 evaluate.py
Out:  results.json + a printed table you can paste straight into the deck.
"""
import glob, json, os, statistics, sys, time
from collections import defaultdict
from detector import detect, redact

PAGES = "pages"


def overlap(a, b):
    return not (a["end"] <= b["start"] or b["end"] <= a["start"])


def main():
    files = sorted(glob.glob(os.path.join(PAGES, "*.html")))
    if not files:
        sys.exit("No pages found. Run: python3 generate_pages.py --n 50")

    tp = defaultdict(int); fp = defaultdict(int); fn = defaultdict(int)
    latencies = []
    leaked_chars = 0; total_sensitive_chars = 0
    raw_bytes = 0; sanitized_bytes = 0
    secret_fields_found = 0; secret_fields_expected = 0

    for f in files:
        html = open(f, encoding="utf-8").read()
        meta = json.load(open(f.replace(".html", ".json"), encoding="utf-8"))
        gold = meta["entities"]

        t0 = time.perf_counter()
        pred, secrets = detect(html)
        latencies.append((time.perf_counter() - t0) * 1000.0)

        matched_gold, matched_pred = set(), set()
        for gi, g in enumerate(gold):
            for pi, p in enumerate(pred):
                if pi in matched_pred:
                    continue
                if p["cls"] == g["cls"] and overlap(p, g):
                    tp[g["cls"]] += 1
                    matched_gold.add(gi); matched_pred.add(pi)
                    break
        for gi, g in enumerate(gold):
            if gi not in matched_gold:
                fn[g["cls"]] += 1
        for pi, p in enumerate(pred):
            if pi not in matched_pred:
                fp[p["cls"]] += 1

        # redaction coverage measured in characters of sensitive text
        sanitized = redact(html, pred, secrets)
        for gi, g in enumerate(gold):
            total_sensitive_chars += len(g["text"])
            if gi not in matched_gold:
                leaked_chars += len(g["text"])

        raw_bytes += len(html.encode()); sanitized_bytes += len(sanitized.encode())

        secret_fields_expected += int(meta["has_password_field"]) + int(meta["has_otp_field"])
        secret_fields_found += len(secrets)

    classes = sorted(set(list(tp) + list(fp) + list(fn)))
    rows, TP = [], 0; FP = 0; FN = 0
    for c in classes:
        t, f_, n = tp[c], fp[c], fn[c]
        TP += t; FP += f_; FN += n
        p = t / (t + f_) if t + f_ else 0.0
        r = t / (t + n) if t + n else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        rows.append((c, t, f_, n, p, r, f1))

    P = TP / (TP + FP) if TP + FP else 0.0
    R = TP / (TP + FN) if TP + FN else 0.0
    F1 = 2 * P * R / (P + R) if P + R else 0.0
    slr = leaked_chars / total_sensitive_chars if total_sensitive_chars else 0.0

    w = 13
    print("\n" + "=" * 78)
    print("NEXORA-PII BASELINE  \u2014  structured detector (DOM + regex + checksum)")
    print("=" * 78)
    print(f"pages: {len(files)}    ground-truth entities: {TP + FN}")
    print("-" * 78)
    print(f"{'CLASS':<{w}}{'TP':>5}{'FP':>5}{'FN':>5}{'PREC':>9}{'RECALL':>9}{'F1':>9}")
    print("-" * 78)
    for c, t, f_, n, p, r, f1 in rows:
        print(f"{c:<{w}}{t:>5}{f_:>5}{n:>5}{p:>9.3f}{r:>9.3f}{f1:>9.3f}")
    print("-" * 78)
    print(f"{'MICRO AVG':<{w}}{TP:>5}{FP:>5}{FN:>5}{P:>9.3f}{R:>9.3f}{F1:>9.3f}")
    print("=" * 78)
    print(f"Sensitive Leakage Rate (chars)   : {slr:.4f}   (lower is better)")
    print(f"Secret fields detected           : {secret_fields_found}/{secret_fields_expected}")
    print(f"Context Exposure Ratio (bytes)   : {sanitized_bytes / raw_bytes:.3f}")
    print(f"Detector latency  mean / p95     : {statistics.mean(latencies):.2f} ms / "
          f"{sorted(latencies)[int(len(latencies) * 0.95) - 1]:.2f} ms")
    print("=" * 78 + "\n")

    json.dump({
        "pages": len(files), "entities": TP + FN,
        "micro": {"precision": P, "recall": R, "f1": F1},
        "per_class": {c: {"tp": t, "fp": f_, "fn": n, "precision": p, "recall": r, "f1": f1}
                      for c, t, f_, n, p, r, f1 in rows},
        "sensitive_leakage_rate": slr,
        "secret_fields": {"found": secret_fields_found, "expected": secret_fields_expected},
        "context_exposure_ratio": sanitized_bytes / raw_bytes,
        "latency_ms": {"mean": statistics.mean(latencies),
                       "p95": sorted(latencies)[int(len(latencies) * 0.95) - 1]},
    }, open("results.json", "w"), indent=2)
    print("wrote results.json")


if __name__ == "__main__":
    main()
