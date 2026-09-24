#!/usr/bin/env python3
"""Local AegisBrowse planner and reproducible scholarship-portal demo."""
from __future__ import annotations

import base64
import binascii
import hashlib
import html
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, ValidationError

BACKEND = os.getenv("AEGIS_BACKEND", "rules")
VLM_BASE = os.getenv("AEGIS_VLM_BASE", "http://127.0.0.1:8001/v1")
VLM_MODEL = os.getenv("AEGIS_VLM_MODEL", "qwen2.5-vl-7b-instruct")
VLM_KEY = os.getenv("AEGIS_VLM_KEY", "not-needed")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_ELEMENTS = 100
ACTIONS = ("CLICK", "TYPE", "SCROLL", "SELECT", "WAIT", "STOP")
TOKEN_VOCAB = {
    "PERSON_n": "a person's name", "EMAIL_n": "an email address",
    "PHONE_n": "a phone number", "AADHAAR_n": "an Aadhaar-style identifier",
    "PAN_n": "a PAN-style identifier", "ACCOUNT_n": "a bank account number",
    "IFSC_n": "a bank branch code", "ADDRESS_n": "a postal address",
    "DOB_n": "a date of birth", "APPLICATION_n": "an application reference",
    "PASSWORD_n": "a password field", "OTP_n": "a one-time-code field",
    "IMAGE_REGION_n": "a blurred image region",
}
log = logging.getLogger("aegisbrowse")
LAST_CONTEXT = {}
LAST_CONTEXT_LOCK = threading.Lock()


class SafeElement(BaseModel):
    id: str
    role: str
    label: str = ""
    rect: List[int] = Field(default_factory=list)
    sensitive: bool = False
    same_origin: bool = True
    options: Optional[List[str]] = None


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    safe_metadata: List[SafeElement] = Field(default_factory=list)
    visual_context: Optional[str] = Field(default=None, max_length=7_100_000)


class PlanResponse(BaseModel):
    action: Literal["CLICK", "TYPE", "SCROLL", "SELECT", "WAIT", "STOP"]
    target_id: Optional[str] = None
    value: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason_code: str = Field(default="unspecified", max_length=160)


app = FastAPI(title="AegisBrowse local planner", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://.*|http://(127\.0\.0\.1|localhost)(:\d+)?)$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type"],
)

STOP_WORDS = {"the", "a", "an", "my", "our", "for", "to", "of", "in", "on", "and",
              "or", "please", "can", "you", "i", "me", "with", "from", "this", "that"}


def _toks(value: str) -> List[str]:
    return [term for term in re.split(r"[^a-z0-9]+", (value or "").lower())
            if len(term) > 2 and term not in STOP_WORDS]


def _dump(model):
    return model.model_dump(exclude_none=True) if hasattr(model, "model_dump") else model.dict(exclude_none=True)


def decode_visual_context(value: Optional[str]) -> bytes:
    if not value:
        return b""
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="visual_context is not valid Base64") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="visual_context exceeds 5 MiB")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=422, detail="visual_context must be a PNG")
    return raw


def plan_rules(request: PlanRequest) -> PlanResponse:
    goal = _toks(request.goal)
    best, best_score = None, 0.0
    for element in request.safe_metadata:
        if element.sensitive or not element.same_origin or element.role not in ("button", "link", "combobox", "textbox"):
            continue
        label = _toks(element.label)
        if not label:
            continue
        overlap = sum(1 for term in goal if any(word == term or word.startswith(term) or term.startswith(word) for word in label))
        score = overlap / max(1, len(goal)) + (0.15 if element.role in ("button", "link") else 0)
        if score > best_score:
            best, best_score = element, score
    if not best or best_score < 0.2:
        return PlanResponse(action="STOP", confidence=0.3, reason_code="no disclosed element matches goal")
    confidence = round(min(0.95, best_score), 2)
    if best.role == "textbox":
        return PlanResponse(action="TYPE", target_id=best.id, value="", confidence=confidence,
                            reason_code="goal names disclosed text field")
    if best.role == "combobox":
        return PlanResponse(action="SELECT", target_id=best.id, value=(best.options or [""])[0],
                            confidence=min(0.9, confidence), reason_code="goal names disclosed selection")
    return PlanResponse(action="CLICK", target_id=best.id, confidence=confidence,
                        reason_code="goal terms match disclosed control")


SYSTEM = f"""You plan one action for a privacy-preserving browser agent. You receive only a locally
sanitized PNG, a sanitized goal, and disclosed safe elements. Typed tokens mean: {json.dumps(TOKEN_VOCAB)}.
Never target sensitive elements. Return exactly one JSON object with action in {ACTIONS}, target_id from the
disclosed set when required, optional value, confidence from 0 to 1, and a short reason_code."""


def plan_vlm(request: PlanRequest) -> PlanResponse:
    import urllib.request
    content = [{"type": "text", "text": json.dumps({
        "goal": request.goal, "safe_metadata": [_dump(item) for item in request.safe_metadata]})}]
    if request.visual_context:
        content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + request.visual_context}})
    payload = json.dumps({"model": VLM_MODEL, "temperature": 0, "max_tokens": 300,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]}).encode()
    upstream = urllib.request.Request(f"{VLM_BASE}/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {VLM_KEY}"})
    with urllib.request.urlopen(upstream, timeout=12) as response:
        body = json.loads(response.read())
    text = body["choices"][0]["message"]["content"].strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    return PlanResponse(**json.loads(text))


@app.get("/health")
def health():
    return {"ok": True, "backend": BACKEND, "version": app.version,
            "actions": list(ACTIONS), "limits": {"image_bytes": MAX_IMAGE_BYTES, "elements": MAX_ELEMENTS}}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/demo")


@app.post("/plan", response_model=PlanResponse)
def plan(request: PlanRequest):
    started = time.perf_counter()
    if len(request.safe_metadata) > MAX_ELEMENTS:
        raise HTTPException(status_code=413, detail=f"safe_metadata exceeds {MAX_ELEMENTS} elements")
    image = decode_visual_context(request.visual_context)
    receipt = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "goal": request.goal,
        "safe_metadata": [_dump(item) for item in request.safe_metadata],
        "visual_context": request.visual_context or "",
        "image_bytes": len(image),
        "image_sha256": hashlib.sha256(image).hexdigest() if image else None,
    }
    with LAST_CONTEXT_LOCK:
        LAST_CONTEXT.clear()
        LAST_CONTEXT.update(receipt)
    try:
        response = plan_vlm(request) if BACKEND == "openai" else plan_rules(request)
    except (ValidationError, json.JSONDecodeError) as error:
        response = PlanResponse(action="STOP", confidence=0.0,
                                reason_code=f"planner schema failure: {type(error).__name__}")
    except Exception as error:
        log.warning("VLM unavailable (%s); using deterministic planner", type(error).__name__)
        response = plan_rules(request)
    allowed_ids = {item.id for item in request.safe_metadata}
    if response.target_id and response.target_id not in allowed_ids:
        response = PlanResponse(action="STOP", confidence=0.0, reason_code="planner targeted undisclosed element")
    goal_hash = hashlib.sha256(request.goal.encode()).hexdigest()[:12]
    log.info("goal_hash=%s elements=%d image_bytes=%d action=%s elapsed_ms=%d",
             goal_hash, len(request.safe_metadata), len(image), response.action,
             round((time.perf_counter() - started) * 1000))
    return response


@app.get("/inspector/data")
def inspector_data():
    with LAST_CONTEXT_LOCK:
        receipt = dict(LAST_CONTEXT)
    receipt.pop("visual_context", None)
    return {"available": bool(receipt), **receipt}


@app.get("/inspector", response_class=HTMLResponse)
def inspector():
    with LAST_CONTEXT_LOCK:
        receipt = dict(LAST_CONTEXT)
    if not receipt:
        content = """<section class='empty'><h2>No planner request received yet</h2>
<p>Run one AegisBrowse step on the demo portal, then refresh this page.</p></section>"""
    else:
        metadata = receipt.get("safe_metadata", [])
        rows = "".join(
            f"<tr><td>{html.escape(str(item.get('id','')))}</td>"
            f"<td>{html.escape(str(item.get('role','')))}</td>"
            f"<td>{html.escape(str(item.get('label','')))}</td>"
            f"<td>{html.escape(str(item.get('same_origin','')))}</td></tr>"
            for item in metadata
        ) or "<tr><td colspan='4'>No elements disclosed</td></tr>"
        encoded = receipt.get("visual_context", "")
        visual = (f"<img alt='Exact sanitized planner input' src='data:image/png;base64,{encoded}'>"
                  if encoded else "<p>No visual context was sent.</p>")
        content = f"""<section class='metrics'>
<div><small>Received</small><b>{html.escape(receipt['received_at'])}</b></div>
<div><small>Sanitized goal</small><b>{html.escape(receipt['goal'])}</b></div>
<div><small>Image bytes</small><b>{receipt['image_bytes']:,}</b></div>
<div><small>Elements disclosed</small><b>{len(metadata)}</b></div></section>
<section class='grid'><article><div class='head'><h2>Exact image received by server</h2><span>SANITIZED CROP</span></div>
<div class='image'>{visual}</div><code>SHA-256 {html.escape(receipt.get('image_sha256') or 'none')}</code></article>
<article><div class='head'><h2>Exact metadata received</h2><span>SAFE STRUCTURE</span></div>
<table><thead><tr><th>ID</th><th>Role</th><th>Label</th><th>Same origin</th></tr></thead><tbody>{rows}</tbody></table></article></section>
<section class='proof'><strong>Server-side receipt</strong><p>This page is generated only from the last <code>/plan</code> request. Raw identity data absent here was not provided to the planner.</p></section>"""
    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<meta http-equiv='refresh' content='5'><title>AegisBrowse Server Receipt</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#071115;color:#e8f8f8;font:14px system-ui}}header{{padding:22px 4vw;border-bottom:1px solid #214149;display:flex;justify-content:space-between}}header h1{{margin:3px 0 0}}header small,.metrics small{{color:#71a0a6;text-transform:uppercase;letter-spacing:1px}}header span,.head span{{color:#62e0b8;border:1px solid #286752;border-radius:99px;padding:7px 10px;font-size:10px;font-weight:800}}main{{padding:24px 4vw}}.metrics{{display:grid;grid-template-columns:1.2fr 2fr .7fr .7fr;gap:12px}}.metrics div,.grid article,.proof,.empty{{background:#0c2025;border:1px solid #214149;border-radius:14px;padding:15px}}.metrics b{{display:block;margin-top:5px;font-size:13px}}.grid{{display:grid;grid-template-columns:1.25fr 1fr;gap:14px;margin-top:14px}}.head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}h2{{margin:0;font-size:15px}}.image{{min-height:380px;display:grid;place-items:center;background:#03090b;border-radius:9px;padding:12px}}.image img{{max-width:100%;max-height:520px}}code{{display:block;margin-top:10px;color:#72aaa9;font-size:10px;word-break:break-all}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 8px;border-bottom:1px solid #1d3940;text-align:left;font-size:11px}}th{{color:#70aaa9}}.proof{{margin-top:14px;border-color:#276954;background:#0c2b25}}.proof strong{{color:#64e1b5}}.proof p{{margin:4px 0 0;color:#a5c7c2}}.proof code{{display:inline;margin:0;color:inherit}}.empty{{max-width:650px;margin:80px auto;text-align:center;padding:40px}}
</style></head><body><header><div><small>NEXORA · SIH26171</small><h1>What the server actually received</h1></div><span>RAW SCREEN NEVER ACCEPTED</span></header><main>{content}</main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.get("/demo", response_class=HTMLResponse)
def demo():
    return """<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>National Scholarship Portal — Demo</title><style>
*{box-sizing:border-box}body{margin:0;background:#eef4f6;color:#18343d;font:16px system-ui}.top{background:#092f45;color:white;padding:18px 6vw;display:flex;justify-content:space-between}.badge{color:#58e0c2;font-weight:800}.wrap{max-width:980px;margin:34px auto;padding:0 18px}.card{background:white;border-radius:18px;padding:28px;box-shadow:0 12px 35px #1233}.profile{display:grid;grid-template-columns:110px 1fr;gap:22px;align-items:center}.avatar{width:100px;height:100px;border-radius:18px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:13px 30px;margin:22px 0}.field{padding:12px;border-bottom:1px solid #dce8eb}.field b{display:block;font-size:12px;color:#67818a}.status{color:#08765e;font-weight:800}.actions{display:flex;gap:12px;flex-wrap:wrap}.btn{display:inline-block;border:0;border-radius:10px;padding:13px 18px;background:#0e7180;color:white;text-decoration:none;font-weight:800}.muted{background:#dce8eb;color:#36545d}.note{margin-top:20px;padding:12px;border-left:4px solid #22b9a7;background:#effbf8}</style></head>
<body><div class='top'><strong>National Scholarship Portal</strong><span class='badge'>SYNTHETIC DEMO — NO REAL DATA</span></div>
<main class='wrap'><section class='card'><div class='profile'><img class='avatar' alt='Applicant photograph' src='/demo/avatar.svg'>
<div><h1>Scholarship Application</h1><p>Application Summary · Academic Year 2026–27</p><span class='status'>✓ Approved</span></div></div>
<div class='grid'><div class='field'><b>Applicant Name</b>Mohammed Izhan Raza</div><div class='field'><b>Application ID</b>SCH482913</div>
<div class='field'><b>PAN</b>ABCDE1234F</div><div class='field'><b>Aadhaar</b>2345 6789 0123</div>
<div class='field'><b>Email</b>student@example.in</div><div class='field'><b>Mobile</b>9876543210</div></div>
<div class='actions'><a id='download-certificate' class='btn' href='/demo/certificate' download>Download Certificate</a>
<button class='btn muted' type='button'>Print</button><a class='btn muted' href='https://example.com/help'>Help</a><button class='btn muted' type='button'>Log out</button></div>
<div class='note'>Use the extension task: <b>Download my scholarship certificate</b>.</div></section></main></body></html>"""


@app.get("/demo/avatar.svg")
def avatar():
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><rect width='120' height='120' rx='18' fill='#c8e4e7'/><circle cx='60' cy='45' r='22' fill='#527985'/><path d='M22 112c5-27 20-40 38-40s33 13 38 40' fill='#527985'/></svg>"""
    return Response(svg, media_type="image/svg+xml")


@app.get("/demo/certificate")
def certificate():
    body = b"NEXORA AegisBrowse synthetic scholarship certificate\nStatus: Approved\n"
    return Response(body, media_type="text/plain",
                    headers={"Content-Disposition": "attachment; filename=synthetic_scholarship_certificate.txt"})
