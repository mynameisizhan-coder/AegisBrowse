#!/usr/bin/env python3
"""Peak memory and CPU time of the local pipeline over a page set.
    python resource_probe.py --dir pages_v3 --selective 1
Measures this Python process only (OCR runs as a child Tesseract process,
whose time is included in wall clock but not in process CPU)."""
import argparse, glob, json, os, platform, time
import psutil, runtime

ap = argparse.ArgumentParser(); ap.add_argument("--dir", default="pages_v3")
ap.add_argument("--selective", type=int, default=1); a = ap.parse_args()
proc = psutil.Process()
pages = sorted(s[:-4] for s in glob.glob(os.path.join(a.dir, "test_*.png")))
base = proc.memory_info().rss
peak = base; cpu0 = proc.cpu_times(); w0 = time.perf_counter(); o0 = runtime.STATS["ocr_calls"]
for stem in pages:
    runtime.run(stem + ".png", json.load(open(stem + ".dom.json")), selective=bool(a.selective), narrow=False)
    peak = max(peak, proc.memory_info().peak_wset if hasattr(proc.memory_info(), "peak_wset") else proc.memory_info().rss)
cpu1 = proc.cpu_times(); n = len(pages)
print(json.dumps(dict(dir=a.dir, selective=bool(a.selective), pages=n,
    peak_working_set_mb=round(peak / 2**20, 1), baseline_rss_mb=round(base / 2**20, 1),
    cpu_ms_per_page=round(((cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)) * 1000 / n, 1),
    wall_ms_per_page=round((time.perf_counter() - w0) * 1000 / n, 1),
    ocr_calls_per_page=round((runtime.STATS["ocr_calls"] - o0) / n, 2),
    cpu=platform.processor(), cores=psutil.cpu_count(), ram_gb=round(psutil.virtual_memory().total / 2**30, 1))))
