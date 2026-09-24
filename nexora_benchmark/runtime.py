#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AegisBrowse RUNTIME pipeline.

HARD RULE: this module may only read
    - the rendered screenshot (pixels)
    - the DOM snapshot a browser extension can obtain at runtime
      (rects, tag, input type, autocomplete, label text, visible text)
It must NEVER open a *.gt.json file. Ground truth is for the scorer only.

Layers, so they can be ablated independently:
    L1  structured : DOM label hints + regex + Verhoeff checksum
    L2  contextual : entity HEURISTICS (regex/gazetteer) for names and
                     addresses in free text. NOT a learned NER model.
    L3  visual     : CV detector for UI elements and image regions
"""
import os, re, subprocess, tempfile
import cv2
import numpy as np

# ───────────────────────── shared PII patterns ─────────────────────────
_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
      [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
      [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
      [9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
      [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
      [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def verhoeff_ok(s):
    d = re.sub(r"\D", "", s)
    if len(d) != 12:
        return False
    c = 0
    for i, ch in enumerate(reversed(d)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("LICENCE", re.compile(r"\b[A-Z]{2}\d{2}\s\d{11}\b")),
    ("VEHICLE", re.compile(r"\b[A-Z]{2}\d{2}\s[A-Z]{2}\s\d{4}\b")),
    ("HEALTH_ID", re.compile(r"\b\d{4}-\d{4}-\d{4}\b")),
    ("PATIENT_ID", re.compile(r"\bPT\d{7}\b")),
    ("APPOINTMENT", re.compile(r"\bAPT\d{6}\b")),
    ("PROPERTY_ID", re.compile(r"\bPID\d{7}\b")),
    ("GRIEVANCE", re.compile(r"\bGRV\d{6}\b")),
    ("EMPLOYEE_ID", re.compile(r"\bEMP\d{5}\b")),
    ("APPLICATION", re.compile(r"\b(?:APP|REF|SCH|ADM)\d{6}\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("DOB", re.compile(r"\b\d{2}[/-]\d{2}[/-](?:19|20)\d{2}\b")),
    ("PHONE", re.compile(r"(?:\+91[\s-]?)?\b[6-9]\d{9}\b")),
    ("ACCOUNT", re.compile(r"\b\d{11,16}\b")),
]

LABEL_HINTS = {
    "AADHAAR": ["aadhaar", "aadhar", "uid"], "PAN": ["pan"],
    "ACCOUNT": ["account"], "IFSC": ["ifsc"], "EMAIL": ["email", "e-mail"],
    "PHONE": ["mobile", "phone"], "DOB": ["date of birth", "dob"],
    "PERSON": ["name", "applicant", "student", "candidate", "employee"],
    "APPLICATION": ["application id", "application no", "reference"],
    "ADDRESS": ["address"],
    "HEALTH_ID": ["health id", "abha"], "PATIENT_ID": ["patient id"],
    "APPOINTMENT": ["appointment"], "PROPERTY_ID": ["property id"],
    "GRIEVANCE": ["grievance"], "EMPLOYEE_ID": ["employee id"],
    "LICENCE": ["licence", "license"], "VEHICLE": ["vehicle", "registration no"],
}

# L2 contextual entity heuristics (regex + stop-list). Not a learned NER model.
ADDRESS_RE = re.compile(
    r"\b\d{1,4},\s?[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*,\s?[A-Z][A-Za-z]+\s?-\s?\d{6}\b")
NAME_RE = re.compile(r"\b[A-Z][a-z]{2,11}\s[A-Z][a-z]{2,11}\b")
NON_NAME = {"Scholarship Status", "Download Certificate", "Application Summary",
            "Academic Year", "State Education", "Login Password", "Enter OTP",
            "National Scholarship", "Municipal Services", "District Health",
            "Employee Self", "Cooperative Bank", "Transport Department",
            "University Admissions", "Board", "Portal", "Records", "Service"}


# ───────────────────────── L1 structured ─────────────────────────
def classify_text(text, label=""):
    """Assign a PII class from the text itself plus the DOM label. No ground truth."""
    low = label.lower()
    hinted = None
    for cls, hints in LABEL_HINTS.items():
        if any(h in low for h in hints):
            hinted = cls
            break
    t = text.strip()
    if not t:
        return None
    # a DOM label naming the class outranks a generic pattern match,
    # provided the value really looks like that class
    if hinted:
        for cls, pat in PATTERNS:
            if cls == hinted:
                m = pat.search(t)
                if m and not (cls == 'AADHAAR' and not verhoeff_ok(m.group())):
                    return cls
                break
    for cls, pat in PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        if cls == "AADHAAR" and not verhoeff_ok(m.group()):
            continue
        if cls == "ACCOUNT" and verhoeff_ok(m.group()):
            continue
        if cls == "ACCOUNT" and hinted not in (None, "ACCOUNT"):
            continue
        return cls
    if hinted == "PERSON" and NAME_RE.fullmatch(t):
        return "PERSON"
    if hinted and hinted not in ("ACCOUNT",):
        return hinted if hinted != "PERSON" else None
    return None


def layer_structured(dom):
    """DOM-declared secrets + labelled/patterned values."""
    out = []
    for el in dom["elements"]:
        it = el.get("input_type")
        if it in ("password", "otp"):
            out.append(dict(box=el["rect"], cls=it.upper(), mode="blackout",
                            layer="L1", src="dom-input-type"))
            continue
        cls = classify_text(el.get("text", ""), el.get("label", ""))
        if cls:
            mode = "blackout" if cls in ("AADHAAR", "PAN", "ACCOUNT") else "token"
            out.append(dict(box=el["rect"], cls=cls, mode=mode, layer="L1",
                            src="dom-label+regex"))
    return out


# ───────────────────────── L2 contextual (NER-lite) ─────────────────────────
def layer_contextual(dom, already):
    """Heuristic contextual entity detection: finds names/addresses in free
    text that L1 could not match. Regex + stop-list, not a learned NER model."""
    covered = {tuple(a["box"]) for a in already}
    out = []
    for el in dom["elements"]:
        if tuple(el["rect"]) in covered or el.get("input_type"):
            continue
        txt = el.get("text", "")
        if len(txt) < 25:
            continue
        addr_spans = list(ADDRESS_RE.finditer(txt))
        for m in addr_spans:
            out.append(dict(box=el["rect"], cls="ADDRESS", mode="token",
                            layer="L2", src="heuristic-address", span=m.group()))
        if addr_spans:
            continue          # do not also emit PERSON from inside an address
        for m in NAME_RE.finditer(txt):
            if m.group() in NON_NAME:
                continue
            out.append(dict(box=el["rect"], cls="PERSON", mode="token",
                            layer="L2", src="heuristic-person", span=m.group()))
    return out


# ───────────────────────── L3 visual ─────────────────────────
def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, x2 - x1), max(0, y2 - y1)
    inter = iw * ih
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua else 0.0


def _nms(boxes, thr=0.45):
    boxes = sorted(boxes, key=lambda d: -d["score"])
    keep = []
    for b in boxes:
        if all(_iou(b["box"], k["box"]) < thr for k in keep):
            keep.append(b)
    return keep


def detect_ui(img_bgr):
    """Classical-CV UI detector. 'score' is a heuristic rule score, NOT a
    learned probability. Replaced by an ONNX model at milestone M1."""
    H, W = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.dilate(cv2.Canny(gray, 30, 110), np.ones((3, 3), np.uint8), 1)
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < 40 or h < 22 or w > W * 0.85 or h > H * 0.75 or y < 66:
            continue
        patch = img_bgr[y:y+h, x:x+w]
        if patch.size == 0:
            continue
        mean = patch.reshape(-1, 3).mean(axis=0)
        std = float(patch.reshape(-1, 3).std())
        inner = gray[y+4:y+h-4, x+4:x+w-4]
        if inner.size == 0:
            continue
        ink = inner < 130
        frac = float(ink.mean())
        if frac > 0.002:
            cols = np.where(ink.any(axis=0))[0]
            centroid = cols.mean() / inner.shape[1] if len(cols) else 0.5
            dark_ink = float(inner[ink].mean())
        else:
            centroid, dark_ink = 0.5, 255.0
        centred = abs(centroid - 0.5) < 0.20
        ar = w / float(h)
        if mean.mean() < 140 and 1.8 < ar < 7.5 and 28 < h < 70:
            cls, sc = "button", 0.90
        elif w > 110 and h > 110 and std < 48:
            cls, sc = "image_region", 0.85
        elif 1.6 < ar < 10.0 and 26 < h < 72 and mean.mean() > 170:
            # Colour tint is a stronger, position-independent signal than text
            # centering, so a green-tinted status chip is resolved first --
            # otherwise short, incidentally-centered text (e.g. "APPROVED")
            # can shadow it into the button branch below.
            if mean[1] > mean[0] + 3:
                cls, sc = "status_block", 0.75
            # Text centering alone is a fragile button/value-field discriminator:
            # a wide data field can have visually "centered" text purely by
            # coincidence of string length. Real buttons in this UI language are
            # tightly fit to their label (<=220px); anything wider is a data
            # field regardless of how its text happens to sit.
            elif centred and dark_ink < 120 and frac > 0.02 and w < 220:
                cls, sc = "button", 0.80
            elif frac < 0.035 or dark_ink > 135:
                cls, sc = "input", 0.78
            else:
                cls, sc = "value_chip", 0.76
        else:
            continue
        boxes.append(dict(cls=cls, box=[x, y, x + w, y + h], score=sc))
    return _nms(boxes)


def ocr_words(img_bgr, box):
    """Word-level OCR boxes inside a region, for span-level redaction."""
    x1, y1, x2, y2 = [int(v) for v in box]
    crop = img_bgr[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        return []
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        cv2.imwrite(f.name, crop); p = f.name
    try:
        r = subprocess.run(["tesseract", p, "stdout", "--psm", "6", "tsv"],
                           capture_output=True, text=True, timeout=25)
        out = []
        for line in r.stdout.splitlines()[1:]:
            c = line.split("\t")
            if len(c) < 12 or not c[11].strip():
                continue
            try:
                L, T, Wd, Hg = int(c[6]), int(c[7]), int(c[8]), int(c[9])
            except ValueError:
                continue
            out.append(dict(text=c[11].strip(),
                            box=[x1 + L, y1 + T, x1 + L + Wd, y1 + T + Hg]))
        return out
    except Exception:
        return []
    finally:
        os.unlink(p)


def span_boxes(img_bgr, region, phrase):
    """Map a detected entity string onto the word boxes that spell it."""
    words = ocr_words(img_bgr, region)
    if not words:
        return None
    want = [w for w in re.split(r"\s+", phrase) if w]
    norm = lambda s: re.sub(r"[^A-Za-z0-9]", "", s).lower()
    tgt = [norm(w) for w in want if norm(w)]
    if not tgt:
        return None
    seq = [norm(w["text"]) for w in words]
    for i in range(len(seq)):
        hit = [j for j in range(i, min(i + len(tgt) + 3, len(seq))) if seq[j] and seq[j] in tgt]
        if len(hit) >= max(1, len(tgt) - 1):
            sel = [words[j]["box"] for j in hit]
            return [min(b[0] for b in sel) - 3, min(b[1] for b in sel) - 3,
                    max(b[2] for b in sel) + 3, max(b[3] for b in sel) + 3]
    return None


def ocr(img_bgr, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    crop = img_bgr[max(0, y1-2):y2+2, max(0, x1-2):x2+2]
    if crop.size == 0:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        cv2.imwrite(f.name, crop)
        p = f.name
    try:
        r = subprocess.run(["tesseract", p, "stdout", "--psm", "7"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip()
    except Exception:
        return ""
    finally:
        os.unlink(p)


def layer_visual(img_bgr, dets, use_ocr=True):
    """Pixel-only path: image regions are sensitive; text inside detected
    chips is OCR'd and classified. Uses no DOM and no ground truth."""
    out = []
    for d in dets:
        if d["cls"] == "image_region":
            out.append(dict(box=d["box"], cls="PHOTO", mode="blur",
                            layer="L3", src="vision-image-region"))
        elif d["cls"] == "value_chip" and use_ocr:
            cls = classify_text(ocr(img_bgr, d["box"]))
            if cls:
                mode = "blackout" if cls in ("AADHAAR", "PAN", "ACCOUNT") else "token"
                out.append(dict(box=d["box"], cls=cls, mode=mode,
                                layer="L3", src="vision-ocr"))
    return out


# ───────────────────────── pipeline ─────────────────────────
def narrow_spans(img_bgr, plan):
    """Shrink block-level prose predictions to the words of the entity itself.
    Directly improves redaction precision (over-redaction)."""
    for p in plan:
        if p.get("span") and p["layer"] == "L2":
            b = span_boxes(img_bgr, p["box"], p["span"])
            if b:
                p["box"] = b
                p["narrowed"] = True
    return plan


def run(png_path, dom, layers=("L1", "L2", "L3"), use_ocr=True, narrow=True):
    """Returns (ui_detections, redaction_plan). Ground truth is never touched."""
    img = cv2.imread(png_path)
    dets = detect_ui(img) if "L3" in layers else []
    plan = []
    if "L1" in layers:
        plan += layer_structured(dom)
    if "L2" in layers:
        plan += layer_contextual(dom, plan)
    if "L3" in layers:
        plan += layer_visual(img, dets, use_ocr=use_ocr)
    if narrow and use_ocr:
        plan = narrow_spans(img, plan)
    # de-duplicate overlapping identical-class predictions
    PRIORITY = {"PASSWORD": 0, "OTP": 0, "AADHAAR": 1, "PAN": 1, "ACCOUNT": 1,
                "LICENCE": 2, "VEHICLE": 2, "HEALTH_ID": 2, "ADDRESS": 2}
    plan.sort(key=lambda p: PRIORITY.get(p["cls"], 5))
    final = []
    for p in plan:
        if not any(_iou(q["box"], p["box"]) > 0.55 for q in final):
            final.append(p)
    return dets, final
