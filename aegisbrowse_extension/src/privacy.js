/**
 * AegisBrowse privacy filter (browser port of runtime.py layers L1 and L2).
 *
 * L1  structured : DOM label hints + regex + Verhoeff checksum
 * L2  contextual : entity heuristics for names/addresses in free text
 *                  (regex + stop-list; NOT a learned NER model)
 * L3  visual     : image regions from the perception model; OCR escalation
 *                  is invoked only for regions the DOM could not resolve.
 *
 * Same class names, same priority order and same output shape as the Python
 * reference, so results are directly comparable.
 */

const D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
           [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
           [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
           [9,8,7,6,5,4,3,2,1,0]];
const P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
           [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
           [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]];

function verhoeffOk(s) {
  const d = (s.match(/\d/g) || []).join("");
  if (d.length !== 12) return false;
  let c = 0;
  const rev = d.split("").reverse();
  for (let i = 0; i < rev.length; i++) c = D[c][P[i % 8][+rev[i]]];
  return c === 0;
}

// Order matters: specific patterns are tried before generic PHONE / ACCOUNT.
const PATTERNS = [
  ["EMAIL",       /\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b/],
  ["LICENCE",     /\b[A-Z]{2}\d{2}\s\d{11}\b/],
  ["VEHICLE",     /\b[A-Z]{2}\d{2}\s[A-Z]{2}\s\d{4}\b/],
  ["HEALTH_ID",   /\b\d{4}-\d{4}-\d{4}\b/],
  ["PATIENT_ID",  /\bPT\d{7}\b/],
  ["APPOINTMENT", /\bAPT\d{6}\b/],
  ["PROPERTY_ID", /\bPID\d{7}\b/],
  ["GRIEVANCE",   /\bGRV\d{6}\b/],
  ["EMPLOYEE_ID", /\bEMP\d{5}\b/],
  ["APPLICATION", /\b(?:APP|REF|SCH|ADM)\d{6}\b/],
  ["AADHAAR",     /\b\d{4}\s?\d{4}\s?\d{4}\b/],
  ["PAN",         /\b[A-Z]{5}\d{4}[A-Z]\b/],
  ["IFSC",        /\b[A-Z]{4}0[A-Z0-9]{6}\b/],
  ["DOB",         /\b\d{2}[/-]\d{2}[/-](?:19|20)\d{2}\b/],
  ["PHONE",       /(?:\+91[\s-]?)?\b[6-9]\d{9}\b/],
  ["ACCOUNT",     /\b\d{11,16}\b/],
];

const LABEL_HINTS = {
  AADHAAR: ["aadhaar", "aadhar", "uid"], PAN: ["pan"], ACCOUNT: ["account"],
  IFSC: ["ifsc"], EMAIL: ["email", "e-mail"], PHONE: ["mobile", "phone"],
  DOB: ["date of birth", "dob"], ADDRESS: ["address"],
  PERSON: ["name", "applicant", "student", "candidate", "employee", "patient", "holder"],
  APPLICATION: ["application id", "application no", "reference"],
  HEALTH_ID: ["health id", "abha"], PATIENT_ID: ["patient id"],
  APPOINTMENT: ["appointment"], PROPERTY_ID: ["property id"],
  GRIEVANCE: ["grievance"], EMPLOYEE_ID: ["employee id"],
  LICENCE: ["licence", "license"], VEHICLE: ["vehicle", "registration no"],
};

const ADDRESS_RE = /\b\d{1,4},\s?[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*,\s?[A-Z][A-Za-z]+\s?-\s?\d{6}\b/g;
const NAME_RE = /\b[A-Z][a-z]{2,11}\s[A-Z][a-z]{2,11}\b/g;
const NON_NAME = new Set(["Scholarship Status", "Download Certificate", "Application Summary",
  "Login Password", "Enter OTP", "Visit Status", "Permit Status", "Request Status",
  "Account Status", "Payroll Status", "Download Report", "Download Receipt",
  "Download Statement", "Download Payslip", "Download Permit", "Book Follow"]);

const BLACKOUT = new Set(["AADHAAR", "PAN", "ACCOUNT", "PASSWORD", "OTP"]);
const PRIORITY = { PASSWORD: 0, OTP: 0, AADHAAR: 1, PAN: 1, ACCOUNT: 1,
                   LICENCE: 2, VEHICLE: 2, HEALTH_ID: 2, ADDRESS: 2, IMAGE_REGION: 2 };

function hintFor(label) {
  const low = (label || "").toLowerCase();
  for (const [cls, hints] of Object.entries(LABEL_HINTS)) {
    if (hints.some((h) => low.includes(h))) return cls;
  }
  return null;
}

export function classifyText(text, label = "") {
  const t = (text || "").trim();
  if (!t) return null;
  const hinted = hintFor(label);
  // a DOM label naming the class outranks a generic pattern match
  if (hinted) {
    for (const [cls, re] of PATTERNS) {
      if (cls !== hinted) continue;
      const m = t.match(re);
      if (m && !(cls === "AADHAAR" && !verhoeffOk(m[0]))) return cls;
      break;
    }
  }
  for (const [cls, re] of PATTERNS) {
    const m = t.match(re);
    if (!m) continue;
    if (cls === "AADHAAR" && !verhoeffOk(m[0])) continue;
    if (cls === "ACCOUNT" && verhoeffOk(m[0])) continue;
    if (cls === "ACCOUNT" && hinted && hinted !== "ACCOUNT") continue;
    return cls;
  }
  if (hinted === "PERSON" && /^[A-Z][a-z]{2,11}\s[A-Z][a-z]{2,11}$/.test(t)) return "PERSON";
  if (hinted && hinted !== "PERSON" && hinted !== "ACCOUNT") return hinted;
  return null;
}

function iou(a, b) {
  const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[2], b[2]), y2 = Math.min(a[3], b[3]);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter;
  return ua > 0 ? inter / ua : 0;
}

/** L1 — DOM-declared secrets plus labelled / patterned values. */
export function layerStructured(dom) {
  const out = [];
  for (const el of dom.elements) {
    if (el.role === "image") {
      out.push({ box: el.rect, cls: "IMAGE_REGION", mode: "blur",
                 layer: "L1", src: "dom-image-region" });
      continue;
    }
    if (el.input_type === "password" || el.input_type === "otp") {
      out.push({ box: el.rect, cls: el.input_type.toUpperCase(),
                 mode: "blackout", layer: "L1", src: "dom-input-type" });
      continue;
    }
    const cls = classifyText(el.text, el.label);
    if (cls) {
      out.push({ box: el.rect, cls,
                 mode: BLACKOUT.has(cls) ? "blackout" : "token",
                 layer: "L1", src: "dom-label+regex" });
    }
  }
  return out;
}

/** L2 — contextual entity heuristics over free text. Not a learned NER model. */
export function layerContextual(dom, already) {
  const covered = new Set(already.map((a) => a.box.join(",")));
  const out = [];
  for (const el of dom.elements) {
    if (covered.has(el.rect.join(",")) || el.input_type) continue;
    const txt = el.text || "";
    if (txt.length < 12) continue;
    const addrs = [...txt.matchAll(ADDRESS_RE)];
    for (const m of addrs) {
      out.push({ box: el.rect, cls: "ADDRESS", mode: "token",
                 layer: "L2", src: "heuristic-address", span: m[0] });
    }
    if (addrs.length) continue;      // never also emit PERSON from inside an address
    for (const m of txt.matchAll(NAME_RE)) {
      if (NON_NAME.has(m[0])) continue;
      out.push({ box: el.rect, cls: "PERSON", mode: "token",
                 layer: "L2", src: "heuristic-person", span: m[0] });
    }
  }
  return out;
}

/** L3 — image regions the perception model located are treated as sensitive. */
export function layerVisual(detections) {
  return detections
    .filter((d) => d.cls === "image_region")
    .map((d) => ({ box: d.box, cls: "IMAGE_REGION", mode: "blur",
                   layer: "L3", src: "vision-image-region" }));
}

/**
 * Sanitize natural-language goals before the network boundary. The original
 * goal stays local for intent validation and execution. The server receives
 * only typed tokens such as [PAN_1].
 */
export function sanitizeGoal(goal) {
  let sanitized = String(goal || "");
  const counters = {};
  const mappings = [];
  for (const [cls, source] of PATTERNS) {
    const flags = source.flags.includes("g") ? source.flags : source.flags + "g";
    const re = new RegExp(source.source, flags);
    sanitized = sanitized.replace(re, (value) => {
      if (cls === "AADHAAR" && !verhoeffOk(value)) return value;
      counters[cls] = (counters[cls] || 0) + 1;
      const token = `${cls}_${counters[cls]}`;
      mappings.push({ token, cls, length: value.length });
      return `[${token}]`;
    });
  }
  return { sanitized, mappings };
}

/** Merge layers, resolve overlaps by class priority, return the redaction plan. */
export function buildPlan(dom, detections, layers = ["L1", "L2", "L3"]) {
  let plan = [];
  if (layers.includes("L1")) plan = plan.concat(layerStructured(dom));
  if (layers.includes("L2")) plan = plan.concat(layerContextual(dom, plan));
  if (layers.includes("L3")) plan = plan.concat(layerVisual(detections));
  plan.sort((a, b) => (PRIORITY[a.cls] ?? 5) - (PRIORITY[b.cls] ?? 5));
  const final = [];
  for (const p of plan) {
    if (!final.some((q) => iou(q.box, p.box) > 0.55)) final.push(p);
  }
  return final;
}

/**
 * Apply the plan to the captured pixels. Returns a sanitized bitmap plus the
 * token table. Blackout and blur happen here, before anything is serialized.
 */
export async function applyRedaction(bitmap, plan) {
  const cv = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = cv.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);

  const counters = {};
  const tokens = [];
  for (const p of plan) {
    const [x1, y1, x2, y2] = p.box.map(Math.round);
    const w = x2 - x1, h = y2 - y1;
    if (w <= 0 || h <= 0) continue;
    counters[p.cls] = (counters[p.cls] || 0) + 1;
    const token = `${p.cls}_${counters[p.cls]}`;
    tokens.push({ token, cls: p.cls, box: p.box, layer: p.layer });

    if (p.mode === "blur") {
      ctx.save();
      ctx.beginPath(); ctx.rect(x1, y1, w, h); ctx.clip();
      ctx.filter = "blur(14px)";
      ctx.drawImage(cv, 0, 0);
      ctx.restore();
      ctx.filter = "none";
    } else if (p.mode === "blackout") {
      ctx.fillStyle = "#141414";
      ctx.fillRect(x1, y1, w, h);
    } else {
      ctx.fillStyle = "#e3f1f2";
      ctx.fillRect(x1, y1, w, h);
      ctx.fillStyle = "#0a5f67";
      ctx.font = "600 13px system-ui, sans-serif";
      ctx.fillText(`[${token}]`, x1 + 5, y1 + Math.min(h - 5, 16));
    }
  }
  return { bitmap: cv.transferToImageBitmap(), tokens };
}
