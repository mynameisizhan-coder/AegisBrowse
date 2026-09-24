#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Renders the four proof panels for a HELD-OUT page, using only the runtime
pipeline's own predictions. Ground truth is never opened here.

  panel1_raw.png        the screen as the user sees it
  panel2_detected.png   what the local perception layer predicts
  panel3_structured.png structured layer only  -> address unresolved
  panel4_cascade.png    full cascade           -> address resolved
"""
import argparse, json, os
import cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from runtime import run

FDIR = "/usr/share/fonts/truetype/dejavu/"


def font(sz, bold=False):
    p = FDIR + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(p, sz) if os.path.exists(p) else ImageFont.load_default()


UI_COL = {"button": (14, 124, 134), "input": (181, 104, 15),
          "image_region": (168, 58, 50), "value_chip": (44, 122, 84),
          "status_block": (29, 62, 99)}


def panel_detected(base, dets):
    im = base.convert("RGBA").copy()
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for b in dets:
        x1, y1, x2, y2 = b["box"]
        c = UI_COL.get(b["cls"], (90, 107, 122))
        d.rectangle([x1, y1, x2, y2], outline=c + (255,), width=3)
        tag = b["cls"]
        f = font(12, True)
        tw = d.textlength(tag, font=f)
        ty = max(0, y1 - 17)
        d.rectangle([x1, ty, x1 + tw + 9, ty + 16], fill=c + (235,))
        d.text((x1 + 4, ty + 1), tag, font=f, fill=(255, 255, 255, 255))
    return Image.alpha_composite(im, ov).convert("RGB")


def panel_redacted(base, plan, unresolved=None):
    im = base.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    for p in plan:
        x1, y1, x2, y2 = [int(v) for v in p["box"]]
        if p["mode"] == "blur":
            im.paste(im.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(14)), (x1, y1))
            d.rectangle([x1, y1, x2, y2], outline=(168, 58, 50), width=3)
        elif p["mode"] == "blackout":
            d.rectangle([x1, y1, x2, y2], fill=(20, 20, 20))
        else:
            d.rectangle([x1, y1, x2, y2], fill=(227, 241, 242))
            d.text((x1 + 6, y1 + 7), f"[{p['cls']}_1]", font=font(14, True), fill=(10, 95, 103))
    if unresolved:
        for b in unresolved:
            x1, y1, x2, y2 = [int(v) for v in b]
            for k in range(0, x2 - x1, 14):
                d.line([x1 + k, y1, min(x1 + k + 7, x2), y1], fill=(181, 104, 15), width=3)
                d.line([x1 + k, y2, min(x1 + k + 7, x2), y2], fill=(181, 104, 15), width=3)
            for k in range(0, y2 - y1, 14):
                d.line([x1, y1 + k, x1, min(y1 + k + 7, y2)], fill=(181, 104, 15), width=3)
                d.line([x2, y1 + k, x2, min(y1 + k + 7, y2)], fill=(181, 104, 15), width=3)
            lab = "unresolved \u2192 escalate to NER / OCR"
            f = font(12, True)
            tw = d.textlength(lab, font=f)
            d.rectangle([x1, y1 - 18, x1 + tw + 11, y1 - 1], fill=(181, 104, 15))
            d.text((x1 + 5, y1 - 17), lab, font=f, fill=(255, 255, 255))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="pages_v2/test_003")
    ap.add_argument("--out", default="vision_panels")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    dom = json.load(open(a.page + ".dom.json"))
    base = Image.open(a.page + ".png")

    dets, plan_full = run(a.page + ".png", dom, layers=("L1", "L2", "L3"), use_ocr=True)
    _, plan_l1 = run(a.page + ".png", dom, layers=("L1",), use_ocr=False)

    # regions the structured layer left unresolved = long text nodes it did not cover
    covered = {tuple(p["box"]) for p in plan_l1}
    unresolved = [el["rect"] for el in dom["elements"]
                  if tuple(el["rect"]) not in covered and len(el.get("text", "")) > 40]

    base.convert("RGB").save(f"{a.out}/panel1_raw.png")
    panel_detected(base, dets).save(f"{a.out}/panel2_detected.png")
    panel_redacted(base, plan_l1, unresolved).save(f"{a.out}/panel3_structured.png")
    panel_redacted(base, plan_full).save(f"{a.out}/panel4_cascade.png")
    print(f"{len(dets)} UI detections | L1 plan {len(plan_l1)} | full plan {len(plan_full)}")
    print(f"panels -> {a.out}/")


if __name__ == "__main__":
    main()
