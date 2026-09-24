#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXORA-PII : synthetic benchmark generator
Builds fake Indian-style portal pages with ground-truth PII spans.

Everything here is randomly generated. No real personal data is used.
Run:  python3 generate_pages.py --n 50
Out:  pages/page_XXX.html  +  pages/page_XXX.json (ground truth)
"""
import argparse, json, os, random, re, string

random.seed(20260901)

FIRST = ["Rahul","Priya","Aman","Sneha","Vikram","Ananya","Karthik","Meera",
         "Rohit","Divya","Arjun","Kavya","Suresh","Nisha","Farhan","Ishita"]
LAST  = ["Sharma","Patel","Reddy","Nair","Iyer","Gupta","Singh","Desai",
         "Menon","Joshi","Rao","Kulkarni","Khan","Bose","Pillai","Chauhan"]
CITY  = ["Bengaluru","Pune","Jaipur","Kochi","Indore","Nagpur","Surat","Bhopal"]
STREET= ["MG Road","Nehru Nagar","Gandhi Marg","Station Road","Park Street"]
DOMAIN= ["example.com","mailbox.in","testmail.org","sample.co.in"]
BANKS = ["State Cooperative Bank","Union Regional Bank","Grameen Bank"]

PORTALS = [
    ("National Scholarship Portal",  "scholarship"),
    ("State Education Board",        "education"),
    ("Municipal Services Portal",    "government"),
    ("District Health Records",      "healthcare"),
    ("Employee Self Service",        "hr"),
    ("Cooperative Bank NetBanking",  "banking"),
    ("Transport Department eSeva",   "government"),
    ("University Admissions Portal", "education"),
]

# ── Verhoeff checksum (used by Aadhaar) so synthetic IDs are structurally valid ──
_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
      [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
      [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
      [9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
      [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
      [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_INV = [0,4,3,2,1,5,6,7,8,9]

def verhoeff_check_digit(num_str):
    c = 0
    for i, item in enumerate(reversed(num_str)):
        c = _D[c][_P[(i + 1) % 8][int(item)]]
    return str(_INV[c])

def gen_aadhaar():
    body = str(random.randint(2, 9)) + "".join(random.choice("0123456789") for _ in range(10))
    full = body + verhoeff_check_digit(body)
    return f"{full[0:4]} {full[4:8]} {full[8:12]}"

def gen_pan():
    return ("".join(random.choice(string.ascii_uppercase) for _ in range(5))
            + "".join(random.choice("0123456789") for _ in range(4))
            + random.choice(string.ascii_uppercase))

def gen_phone():
    return random.choice(["+91 ", "+91-", "", "0"]) + random.choice("6789") + "".join(random.choice("0123456789") for _ in range(9))

def gen_email(first, last):
    sep = random.choice([".", "_", ""])
    return f"{first.lower()}{sep}{last.lower()}{random.randint(1,99)}@{random.choice(DOMAIN)}"

def gen_account():
    return "".join(random.choice("0123456789") for _ in range(random.choice([11, 12, 14, 16])))

def gen_ifsc():
    return "".join(random.choice(string.ascii_uppercase) for _ in range(4)) + "0" + \
           "".join(random.choice(string.ascii_uppercase + "0123456789") for _ in range(6))

def gen_dob():
    return f"{random.randint(1,28):02d}/{random.randint(1,12):02d}/{random.randint(1970,2005)}"

def gen_appid():
    return random.choice(["APP", "REF", "SCH", "ADM"]) + str(random.randint(100000, 999999))

def gen_address(city):
    return f"{random.randint(1,299)}, {random.choice(STREET)}, {city} - {random.randint(400000,700000)}"


PROSE_TEMPLATES = [
    "Please confirm that your registered mobile {PHONE} and email {EMAIL} are current before proceeding.",
    "Correspondence regarding this application will be sent to {EMAIL}. Contact {PHONE} for assistance.",
    "The applicant {PERSON} residing at {ADDRESS} has submitted the required documents.",
    "Disbursement will be credited to account {ACCOUNT} held with the branch code {IFSC}.",
    "Records for {PERSON} (born {DOB}) were verified against the submitted identity proof.",
    "If the details for {PERSON} are incorrect, raise a grievance quoting {APPLICATION}.",
]

GENERIC_LABELS = ["Value", "Details", "Entry", "Field", "Particulars", "Information"]

def make_distractors():
    """Values that structurally resemble PII but are not. These create false positives."""
    out = []
    # 12-digit invoice number that FAILS the Verhoeff check -> not an Aadhaar
    while True:
        cand = "".join(random.choice("0123456789") for _ in range(12))
        if verhoeff_check_digit(cand[:11]) != cand[11]:
            out.append(("Invoice Reference", f"{cand[0:4]} {cand[4:8]} {cand[8:12]}"))
            break
    # 10-digit number that is not a valid Indian mobile (starts 2-5)
    out.append(("Token Number", random.choice("2345") + "".join(random.choice("0123456789") for _ in range(9))))
    # PAN-shaped but in a non-PAN field
    out.append(("Form Code", "".join(random.choice(string.ascii_uppercase) for _ in range(5))
                + "".join(random.choice("0123456789") for _ in range(4))
                + random.choice(string.ascii_uppercase)))
    # long digit run that is a transaction id, not an account
    out.append(("Transaction ID", "".join(random.choice("0123456789") for _ in range(13))))
    random.shuffle(out)
    return out[:random.randint(1, 3)]


def build_page(idx, level):
    """Returns (html, meta). level 1=easy labelled, 2=generic labels, 3=prose+distractors."""
    first, last = random.choice(FIRST), random.choice(LAST)
    name = f"{first} {last}"
    city = random.choice(CITY)
    portal, domain = random.choice(PORTALS)

    # Pool of candidate fields; each page uses a random subset -> varied difficulty
    pool = [
        ("PERSON",      "Applicant Name",     name),
        ("EMAIL",       "Registered Email",   gen_email(first, last)),
        ("PHONE",       "Mobile Number",      gen_phone()),
        ("AADHAAR",     "Aadhaar Number",     gen_aadhaar()),
        ("PAN",         "PAN",                gen_pan()),
        ("ACCOUNT",     "Bank Account Number",gen_account()),
        ("IFSC",        "IFSC Code",          gen_ifsc()),
        ("DOB",         "Date of Birth",      gen_dob()),
        ("ADDRESS",     "Address",            gen_address(city)),
        ("APPLICATION", "Application ID",     gen_appid()),
    ]
    random.shuffle(pool)
    n_fields = random.randint(5, len(pool))
    chosen = pool[:n_fields]

    # Non-PII distractors that a naive detector may false-positive on
    distractors = [
        ("Application Status", random.choice(["APPROVED", "UNDER REVIEW", "DISBURSED"])),
        ("Scheme Code", "SCHM" + str(random.randint(1000, 9999))),
        ("Academic Year", f"{random.randint(2022,2026)}-{random.randint(23,27)}"),
        ("Institute PIN", str(random.randint(100000, 999999))),
        ("Helpline", "1800-000-0000"),
        ("Total Amount", f"Rs. {random.randint(5000,90000)}"),
    ]
    random.shuffle(distractors)
    distractors = distractors[:random.randint(2, 4)]

    if level >= 3:
        distractors = distractors + make_distractors()

    rows, gt = [], []
    prose_fields = []
    for i, (cls, label, value) in enumerate(chosen):
        # level 3: move roughly half of the fields into unlabelled prose
        if level >= 3 and cls in ("PHONE", "EMAIL", "PERSON", "ADDRESS", "ACCOUNT",
                                  "IFSC", "DOB", "APPLICATION") and random.random() < 0.5:
            prose_fields.append((cls, value))
            continue
        if level >= 2 and random.random() < 0.45:
            label = random.choice(GENERIC_LABELS)   # label no longer names the class
        rows.append((label, value, cls))
    for label, value in distractors:
        rows.append((label, value, None))
    random.shuffle(rows)

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{portal}</title></head><body>",
        f"<header><h1>{portal}</h1></header>",
        "<main><table id='details'>",
    ]
    for label, value, cls in rows:
        parts.append(f"<tr><td class='label'>{label}</td><td class='value'>{value}</td></tr>")
    parts.append("</table>")

    has_password = random.random() < 0.45
    if has_password:
        parts.append("<form><label>Login Password</label>"
                     "<input type='password' name='pwd' autocomplete='current-password'></form>")
    has_otp = random.random() < 0.3
    if has_otp:
        parts.append("<form><label>Enter OTP</label>"
                     "<input type='text' name='otp' inputmode='numeric' maxlength='6'></form>")

    if prose_fields:
        avail = {c: v for c, v in prose_fields}
        used = []
        for tmpl in random.sample(PROSE_TEMPLATES, len(PROSE_TEMPLATES)):
            keys = re.findall(r"\{(\w+)\}", tmpl)
            if all(k in avail for k in keys) and any(k not in used for k in keys):
                parts.append("<p class='note'>" + tmpl.format(**avail) + "</p>")
                used.extend(keys)
            if all(c in used for c, _ in prose_fields):
                break
        for c, v in prose_fields:
            if c not in used:
                parts.append(f"<p class='note'>Reference on file: {v}</p>")

    parts.append("<button id='btn_download'>Download Certificate</button>")
    parts.append("</main></body></html>")
    html = "\n".join(parts)

    # ground truth = character spans in the rendered HTML
    for label, value, cls in rows:
        if cls is None:
            continue
        start = html.find(value)
        gt.append({"cls": cls, "text": value, "start": start, "end": start + len(value)})
    for cls, value in prose_fields:
        start = html.find(value)
        if start >= 0:
            gt.append({"cls": cls, "text": value, "start": start, "end": start + len(value)})

    meta = {
        "page_id": f"page_{idx:03d}",
        "level": level,
        "domain": domain,
        "portal": portal,
        "has_password_field": has_password,
        "has_otp_field": has_otp,
        "entities": gt,
    }
    return html, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--out", default="pages")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    total = 0
    counts = {1: 0, 2: 0, 3: 0}
    for i in range(a.n):
        level = 1 if i < a.n // 3 else (2 if i < 2 * a.n // 3 else 3)
        counts[level] += 1
        html, meta = build_page(i, level)
        open(os.path.join(a.out, f"page_{i:03d}.html"), "w", encoding="utf-8").write(html)
        json.dump(meta, open(os.path.join(a.out, f"page_{i:03d}.json"), "w", encoding="utf-8"), indent=1)
        total += len(meta["entities"])
    print(f"generated {a.n} pages ({counts[1]} L1 / {counts[2]} L2 / {counts[3]} L3), "
          f"{total} ground-truth PII entities -> {a.out}/")


if __name__ == "__main__":
    main()
