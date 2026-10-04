#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOM-blind stress variant of an existing corpus.

Same screenshots, same ground truth -- only the runtime DOM snapshot is
degraded, simulating content the extension cannot read structurally:
    - every <img> is removed            (photo drawn on canvas / CSS background)
    - ~1/3 of labelled value fields are removed
                                        (text rendered into canvas or an image)

    python make_domblind.py --src pages_v3 --out pages_v3_domblind
"""
import argparse, glob, json, os, random, shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="pages_v3")
    ap.add_argument("--out", default="pages_v3_domblind")
    ap.add_argument("--drop", type=float, default=0.34)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    removed = imgs = 0
    for png in sorted(glob.glob(os.path.join(a.src, "*.png"))):
        stem = png[:-4]
        name = os.path.basename(stem)
        rng = random.Random(name)                 # deterministic per page
        dom = json.load(open(stem + ".dom.json"))
        keep = []
        for el in dom["elements"]:
            if el.get("tag") == "img":
                imgs += 1
                continue
            if el.get("tag") == "div" and el.get("role") == "text" and rng.random() < a.drop:
                removed += 1
                continue
            keep.append(el)
        dom["elements"] = keep
        dom["dom_blind"] = True
        dst = os.path.join(a.out, name)
        json.dump(dom, open(dst + ".dom.json", "w"), indent=1)
        shutil.copy(png, dst + ".png")
        shutil.copy(stem + ".gt.json", dst + ".gt.json")
    print(f"{a.out}: removed {imgs} <img> and {removed} value fields from the DOM")


if __name__ == "__main__":
    main()
