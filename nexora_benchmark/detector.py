#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXORA baseline structured PII detector.
Layer 1 of the cascade: DOM tags + regex + checksum validation + label context.
No ML. This is the floor your NER/OCR/vision layers must improve on.
"""
import re

_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
      [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
      [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
      [9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
      [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
      [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]

def verhoeff_valid(num_str):
    digits = re.sub(r"\D", "", num_str)
    if len(digits) != 12:
        return False
    c = 0
    for i, item in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][int(item)]]
    return c == 0

# label -> class hints taken from the DOM cell text (cheap, high precision)
LABEL_HINTS = {
    "AADHAAR":     ["aadhaar", "aadhar", "uid"],
    "PAN":         ["pan"],
    "ACCOUNT":     ["account number", "account no", "bank account"],
    "IFSC":        ["ifsc"],
    "EMAIL":       ["email", "e-mail"],
    "PHONE":       ["mobile", "phone", "contact number"],
    "DOB":         ["date of birth", "dob", "birth"],
    "ADDRESS":     ["address", "residence"],
    "PERSON":      ["name", "applicant", "student", "candidate", "employee"],
    "APPLICATION": ["application id", "application no", "reference id", "ref id"],
}

PATTERNS = [
    ("EMAIL",   re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PAN",     re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("IFSC",    re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("PHONE",   re.compile(r"(?:\+91[\s-]?|\b0)?[6-9]\d{9}\b")),
    ("DOB",     re.compile(r"\b\d{2}[/-]\d{2}[/-](?:19|20)\d{2}\b")),
    ("ACCOUNT", re.compile(r"\b\d{11,16}\b")),
    ("APPLICATION", re.compile(r"\b(?:APP|REF|SCH|ADM)\d{6}\b")),
]

ROW_RE = re.compile(
    r"<td class='label'>(?P<label>[^<]*)</td><td class='value'>(?P<value>[^<]*)</td>")
PWD_RE = re.compile(r"<input[^>]*type=['\"]password['\"][^>]*>")
OTP_RE = re.compile(r"<input[^>]*name=['\"]otp['\"][^>]*>")


def _classify_label(label_text):
    low = label_text.lower()
    for cls, hints in LABEL_HINTS.items():
        for h in hints:
            if h in low:
                return cls
    return None


def detect(html):
    """Returns (entities, secret_fields).

    entities: [{cls, text, start, end, source}]
    secret_fields: DOM-detected fields that must never leave the device.
    """
    found = {}          # (start,end) -> entity
    secret_fields = []

    # ── Layer A: DOM structure. Label cell names the class of the value cell. ──
    for m in ROW_RE.finditer(html):
        label, value = m.group("label"), m.group("value")
        cls = _classify_label(label)
        if not cls:
            continue
        vs = m.start("value")
        ve = vs + len(value)
        # Validate the value actually looks like that class before trusting the label
        ok = True
        if cls == "AADHAAR":
            ok = verhoeff_valid(value)
        elif cls == "PAN":
            ok = bool(PATTERNS[2][1].fullmatch(value))
        elif cls == "IFSC":
            ok = bool(PATTERNS[3][1].fullmatch(value))
        elif cls == "EMAIL":
            ok = "@" in value
        elif cls == "ACCOUNT":
            ok = value.isdigit() and 9 <= len(value) <= 18
        elif cls == "APPLICATION":
            ok = bool(re.fullmatch(r"[A-Z]{3}\d{6}", value))
        if ok:
            found[(vs, ve)] = {"cls": cls, "text": value, "start": vs, "end": ve, "source": "dom"}

    # ── Layer B: pattern scan over the whole document (catches unlabelled values) ──
    for cls, pat in PATTERNS:
        for m in pat.finditer(html):
            span = (m.start(), m.end())
            if span in found:
                continue
            if any(s <= m.start() < e for s, e in found):
                continue
            val = m.group()
            if cls == "AADHAAR" and not verhoeff_valid(val):
                continue          # checksum kills most false positives
            if cls == "ACCOUNT" and verhoeff_valid(val):
                continue          # it is really an Aadhaar, handled above
            found[span] = {"cls": cls, "text": val, "start": m.start(), "end": m.end(), "source": "regex"}

    # ── Layer C: DOM-declared secrets. Never transmitted, not even tokenized. ──
    for m in PWD_RE.finditer(html):
        secret_fields.append({"cls": "PASSWORD", "start": m.start(), "end": m.end(), "source": "dom"})
    for m in OTP_RE.finditer(html):
        secret_fields.append({"cls": "OTP", "start": m.start(), "end": m.end(), "source": "dom"})

    return sorted(found.values(), key=lambda e: e["start"]), secret_fields


def redact(html, entities, secret_fields):
    """Replace every detected span with a typed placeholder. Returns sanitized text."""
    spans = [(e["start"], e["end"], f"[{e['cls']}_1]") for e in entities]
    spans += [(s["start"], s["end"], f"[{s['cls']}_FIELD]") for s in secret_fields]
    out, last = [], 0
    for s, e, tok in sorted(spans):
        if s < last:
            continue
        out.append(html[last:s]); out.append(tok); last = e
    out.append(html[last:])
    return "".join(out)
