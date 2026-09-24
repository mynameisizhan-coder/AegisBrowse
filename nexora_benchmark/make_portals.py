#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Domain-consistent portal generator.

Each template family has its OWN field vocabulary and action buttons, so a
health portal never shows "Scholarship Status" or "Download Certificate".

Family-level split (guards against generator-family leakage):
    DEV_FAMILIES  -> used while tuning heuristics
    TEST_FAMILIES -> never used for tuning; reported results come only from here
The two groups also differ in layout and theme, not just wording.

Writes per page:
    page.png        screenshot     (runtime input)
    page.dom.json   DOM snapshot   (runtime input, carries no PII labels)
    page.gt.json    ground truth   (EVALUATION ONLY)
"""
import argparse, json, os, random, string, subprocess

W, H = 1280, 720

FIRST = ["Rahul", "Priya", "Aman", "Sneha", "Vikram", "Ananya", "Karthik", "Meera",
         "Rohit", "Divya", "Arjun", "Kavya", "Farhan", "Ishita", "Nikhil", "Tara"]
LAST = ["Sharma", "Patel", "Reddy", "Nair", "Iyer", "Gupta", "Singh", "Desai",
        "Menon", "Joshi", "Rao", "Kulkarni", "Khan", "Pillai", "Bose", "Chauhan"]
CITY = ["Bengaluru", "Pune", "Jaipur", "Kochi", "Indore", "Nagpur", "Surat", "Bhopal"]
STREET = ["MG Road", "Nehru Nagar", "Gandhi Marg", "Station Road", "Park Street"]
DOCTOR = ["Dr. A Krishnan", "Dr. S Bhatt", "Dr. R Mehta", "Dr. N Verma"]

_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
      [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
      [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
      [9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
      [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
      [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_INV = [0,4,3,2,1,5,6,7,8,9]


def _verhoeff(num):
    c = 0
    for i, d in enumerate(reversed(num)):
        c = _D[c][_P[(i + 1) % 8][int(d)]]
    return str(_INV[c])


def val(kind, rng, first="", last=""):
    U, Dg = string.ascii_uppercase, "0123456789"
    if kind == "PERSON":
        return f"{first} {last}"
    if kind == "AADHAAR":
        b = str(rng.randint(2, 9)) + "".join(rng.choice(Dg) for _ in range(10))
        f = b + _verhoeff(b)
        return f"{f[0:4]} {f[4:8]} {f[8:12]}"
    if kind == "PAN":
        return "".join(rng.choice(U) for _ in range(5)) + "".join(rng.choice(Dg) for _ in range(4)) + rng.choice(U)
    if kind == "EMAIL":
        return f"{first.lower()}.{last.lower()}{rng.randint(1,99)}@example.com"
    if kind == "PHONE":
        return "+91 " + rng.choice("6789") + "".join(rng.choice(Dg) for _ in range(9))
    if kind == "ACCOUNT":
        return "".join(rng.choice(Dg) for _ in range(rng.choice([11, 12, 14])))
    if kind == "IFSC":
        return "".join(rng.choice(U) for _ in range(4)) + "0" + "".join(rng.choice(U + Dg) for _ in range(6))
    if kind == "DOB":
        return f"{rng.randint(1,28):02d}/{rng.randint(1,12):02d}/{rng.randint(1975,2005)}"
    if kind == "APPLICATION":
        return rng.choice(["APP", "REF", "SCH", "ADM"]) + str(rng.randint(100000, 999999))
    if kind == "HEALTH_ID":
        return "-".join("".join(rng.choice(Dg) for _ in range(4)) for _ in range(3))
    if kind == "PATIENT_ID":
        return "PT" + str(rng.randint(1000000, 9999999))
    if kind == "APPOINTMENT":
        return "APT" + str(rng.randint(100000, 999999))
    if kind == "PROPERTY_ID":
        return "PID" + str(rng.randint(1000000, 9999999))
    if kind == "GRIEVANCE":
        return "GRV" + str(rng.randint(100000, 999999))
    if kind == "EMPLOYEE_ID":
        return "EMP" + str(rng.randint(10000, 99999))
    if kind == "LICENCE":
        return rng.choice(["KA", "MH", "RJ", "TN"]) + str(rng.randint(10, 99)) + " " + str(rng.randint(10000000000, 99999999999))
    if kind == "VEHICLE":
        return (rng.choice(["KA", "MH", "RJ", "TN"]) + f"{rng.randint(1,60):02d} "
                + "".join(rng.choice(U) for _ in range(2)) + f" {rng.randint(1000,9999)}")
    return ""


FAMILIES = {
    "scholarship": (["National Scholarship Portal", "State Merit Scholarship"],
        [("PERSON", "Applicant Name"), ("APPLICATION", "Application ID"),
         ("AADHAAR", "Aadhaar Number"), ("ACCOUNT", "Bank Account Number"),
         ("IFSC", "IFSC Code"), ("EMAIL", "Registered Email"), ("PHONE", "Mobile Number")],
        "Scholarship Status", ["APPROVED", "DISBURSED"],
        ["Download Certificate", "Print", "Log out"]),
    "hr": (["Employee Self Service", "Payroll Portal"],
        [("PERSON", "Employee Name"), ("EMPLOYEE_ID", "Employee ID"),
         ("PAN", "PAN"), ("ACCOUNT", "Salary Account"), ("IFSC", "IFSC Code"),
         ("EMAIL", "Work Email"), ("PHONE", "Contact Number")],
        "Payroll Status", ["PROCESSED", "PENDING"],
        ["Download Payslip", "Print", "Log out"]),
    "health": (["District Health Records", "State Hospital Portal"],
        [("PERSON", "Patient Name"), ("HEALTH_ID", "Health ID"),
         ("PATIENT_ID", "Patient ID"), ("DOB", "Date of Birth"),
         ("APPOINTMENT", "Appointment ID"), ("PHONE", "Contact Number")],
        "Visit Status", ["COMPLETED", "SCHEDULED"],
        ["Download Report", "Book Follow-up", "Log out"]),
    "municipal": (["Municipal Services Portal", "City Grievance Cell"],
        [("PERSON", "Applicant Name"), ("PROPERTY_ID", "Property ID"),
         ("GRIEVANCE", "Grievance Number"), ("APPLICATION", "Application ID"),
         ("PHONE", "Mobile Number")],
        "Request Status", ["RESOLVED", "IN PROGRESS"],
        ["Download Receipt", "Track Status", "Log out"]),
    "banking": (["Cooperative Bank NetBanking", "Regional Bank Online"],
        [("PERSON", "Account Holder"), ("ACCOUNT", "Account Number"),
         ("IFSC", "IFSC Code"), ("PAN", "PAN"), ("PHONE", "Registered Mobile"),
         ("EMAIL", "Registered Email")],
        "Account Status", ["ACTIVE", "VERIFIED"],
        ["Download Statement", "Print", "Log out"]),
    "transport": (["Transport Department eSeva", "RTO Services"],
        [("PERSON", "Applicant Name"), ("LICENCE", "Licence Number"),
         ("VEHICLE", "Vehicle Number"), ("APPLICATION", "Application ID"),
         ("DOB", "Date of Birth")],
        "Permit Status", ["ISSUED", "UNDER REVIEW"],
        ["Download Permit", "Print", "Log out"]),
}

DEV_FAMILIES = ["scholarship", "hr"]
TEST_FAMILIES = ["health", "municipal", "banking", "transport"]

DEV_THEMES = [
    dict(bg="#ffffff", band="#123a63", chip="#eef3f8", cb="1px solid #d3dde6",
         txt="#17232f", lbl="#5a6b7a", bf="#1d3e63", bt="#ffffff", font="Arial"),
    dict(bg="#fdfcfa", band="#7a4a12", chip="#f7f1e7", cb="1px solid #e0d3bf",
         txt="#241d12", lbl="#6f6355", bf="#8a5a16", bt="#ffffff", font="Verdana"),
]
TEST_THEMES = [
    dict(bg="#f2f5f8", band="#22303d", chip="#ffffff", cb="1px solid #c2ccd6",
         txt="#141b22", lbl="#5e6a76", bf="#ffffff", bt="#22303d", font="Georgia"),
    dict(bg="#eef2f1", band="#0f4c4a", chip="#e2edeb", cb="none",
         txt="#0f1d1c", lbl="#4e6260", bf="#0e7c86", bt="#ffffff", font="Tahoma"),
    dict(bg="#ffffff", band="#4a2a52", chip="#f4eef6", cb="1px solid #d9c9de",
         txt="#1d1420", lbl="#6a5a70", bf="#ffffff", bt="#4a2a52", font="Trebuchet MS"),
]


def build(idx, seed, split):
    rng = random.Random(seed)
    fam = rng.choice(DEV_FAMILIES if split == "dev" else TEST_FAMILIES)
    titles, fields, slabel, svals, btns = FAMILIES[fam]
    th = rng.choice(DEV_THEMES if split == "dev" else TEST_THEMES)
    first, last = rng.choice(FIRST), rng.choice(LAST)
    card_layout = split == "test" and rng.random() < 0.6
    two_col = split == "test"
    outlined = th["bf"] == "#ffffff"

    dom, gt, parts = [], [], []
    parts.append(f'<div style="position:absolute;left:0;top:0;width:{W}px;height:58px;'
                 f'background:{th["band"]};"></div><div style="position:absolute;left:26px;'
                 f'top:17px;color:#fff;font:600 20px {th["font"]};">{rng.choice(titles)}</div>')

    rows = rng.sample(fields, max(4, len(fields) - rng.randint(0, 2)))
    lx = rng.choice([26, 40])
    if card_layout:
        parts.append(f'<div style="position:absolute;left:{lx-12}px;top:86px;width:600px;'
                     f'height:{40+len(rows)*48}px;background:#ffffff;border:1px solid #dbe3ea;"></div>')
    y = 104 if not card_layout else 110
    lw = rng.choice([200, 240])
    vx = lx + lw + rng.choice([18, 30])
    vw = rng.choice([240, 275])
    step = rng.choice([44, 48])
    for cls, label in rows:
        v = val(cls, rng, first, last)
        parts.append(f'<div style="position:absolute;left:{lx}px;top:{y+6}px;width:{lw}px;'
                     f'color:{th["lbl"]};font:400 14px {th["font"]};">{label}</div>')
        parts.append(f'<div style="position:absolute;left:{vx}px;top:{y}px;width:{vw}px;height:32px;'
                     f'background:{th["chip"]};border:{th["cb"]};"><div style="padding:6px 0 0 10px;'
                     f'color:{th["txt"]};font:600 15px {th["font"]};">{v}</div></div>')
        box = [vx, y, vx + vw, y + 32]
        dom.append(dict(tag="div", role="text", rect=box, text=v, label=label))
        gt.append(dict(cls="value_chip", pii=cls, box=box, text=v))
        y += step

    rx = 720 if two_col else lx
    ry = 104 if two_col else y + 18
    parts.append(f'<div style="position:absolute;left:{rx}px;top:{ry+6}px;width:220px;'
                 f'color:{th["lbl"]};font:400 14px {th["font"]};">{slabel}</div>')
    parts.append(f'<div style="position:absolute;left:{rx}px;top:{ry+32}px;width:230px;height:40px;'
                 f'background:#e6f3ec;border:1px solid #2c7a54;"><div style="padding:10px 0 0 13px;'
                 f'color:#2c7a54;font:700 16px {th["font"]};">{rng.choice(svals)}</div></div>')
    dom.append(dict(tag="div", role="status", rect=[rx, ry + 32, rx + 230, ry + 72], text="", label=slabel))
    gt.append(dict(cls="status_block", box=[rx, ry + 32, rx + 230, ry + 72]))

    if rng.random() < 0.8:
        px, py = 1010, 104
        parts.append(f'<div style="position:absolute;left:{px}px;top:{py}px;width:150px;height:180px;'
                     f'background:#c9d2da;border:1px solid #9db2c4;"></div>'
                     f'<div style="position:absolute;left:{px}px;top:{py+82}px;width:150px;'
                     f'text-align:center;color:#5a6b7a;font:400 12px {th["font"]};">photograph</div>')
        dom.append(dict(tag="img", role="image", rect=[px, py, px + 150, py + 180], text="", label="photograph"))
        gt.append(dict(cls="image_region", pii="PHOTO", box=[px, py, px + 150, py + 180]))

    addr = f"{rng.randint(1,299)}, {rng.choice(STREET)}, {rng.choice(CITY)} - {rng.randint(400000,700000)}"
    prx = 720 if two_col else lx
    pry = ry + 92 if two_col else y + 18
    fs = f'400 13px {th["font"]}'
    parts.append(f'<div style="position:absolute;left:{prx}px;top:{pry}px;width:500px;'
                 f'color:{th["lbl"]};font:{fs};">Correspondence will be sent to the address below.</div>')
    # the address lives in its OWN positioned span, exactly as it would in real
    # markup -> the DOM gives a precise rect, so redaction need not mask the
    # surrounding sentence (this is what makes redaction precision meaningful)
    aw = 330
    abox = [prx, pry + 24, prx + aw, pry + 46]
    parts.append(f'<div style="position:absolute;left:{prx}px;top:{pry+24}px;width:{aw}px;'
                 f'height:22px;color:{th["txt"]};font:600 13px {th["font"]};">{addr}</div>')
    extra = f" Attending physician {rng.choice(DOCTOR)}." if fam == "health" else ""
    parts.append(f'<div style="position:absolute;left:{prx}px;top:{pry+52}px;width:500px;'
                 f'color:{th["lbl"]};font:{fs};">Helpdesk 1800-000-0000 for assistance.{extra}</div>')
    dom.append(dict(tag="p", role="text", rect=[prx, pry, prx + 500, pry + 22],
                    text="Correspondence will be sent to the address below.", label=""))
    dom.append(dict(tag="span", role="text", rect=abox, text=addr, label=""))
    dom.append(dict(tag="p", role="text", rect=[prx, pry + 52, prx + 500, pry + 74],
                    text=f"Helpdesk 1800-000-0000 for assistance.{extra}", label=""))
    gt.append(dict(cls="prose_pii", pii="ADDRESS", box=abox, text=addr))

    fy = max(y + 40, 486)
    ix = lx
    for nm, ph, dt in [("Login Password", "\u2022" * 8, "password"), ("Enter OTP", "6-digit code", "otp")]:
        iw = 270 if dt == "password" else 165
        parts.append(f'<div style="position:absolute;left:{ix}px;top:{fy}px;width:200px;'
                     f'color:{th["lbl"]};font:400 13px {th["font"]};">{nm}</div>'
                     f'<div style="position:absolute;left:{ix}px;top:{fy+24}px;width:{iw}px;height:38px;'
                     f'background:#ffffff;border:1.5px solid #9db2c4;"><div style="padding:10px 0 0 11px;'
                     f'color:#93a1ae;font:400 14px {th["font"]};">{ph}</div></div>')
        box = [ix, fy + 24, ix + iw, fy + 62]
        dom.append(dict(tag="input", role="textbox", rect=box, text="", label=nm, input_type=dt,
                        autocomplete="current-password" if dt == "password" else "one-time-code"))
        gt.append(dict(cls="input", secret=dt.upper(), box=box))
        ix += iw + 40

    by, bx = fy + 86, lx
    for cap in btns:
        bw = 190 if len(cap) > 10 else 130
        fill = th["bf"] if not outlined else "#ffffff"
        brd = "none" if not outlined else f'1.5px solid {th["bt"]}'
        parts.append(f'<div style="position:absolute;left:{bx}px;top:{by}px;width:{bw}px;height:42px;'
                     f'background:{fill};border:{brd};"><div style="padding:12px 0 0 0;text-align:center;'
                     f'color:{th["bt"]};font:700 14px {th["font"]};">{cap}</div></div>')
        dom.append(dict(tag="button", role="button", rect=[bx, by, bx + bw, by + 42], text=cap, label=cap))
        gt.append(dict(cls="button", box=[bx, by, bx + bw, by + 42]))
        bx += bw + 26

    html = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>*{{margin:0;padding:0;'
            f'box-sizing:border-box;}}body{{width:{W}px;height:{H}px;background:{th["bg"]};'
            f'position:relative;font-family:{th["font"]},Arial,sans-serif;overflow:hidden;}}'
            f'</style></head><body>{"".join(parts)}</body></html>')
    return html, dom, gt, fam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", type=int, default=12)
    ap.add_argument("--test", type=int, default=48)
    ap.add_argument("--out", default="pages_v2")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    n = 0
    for split, count in (("dev", a.dev), ("test", a.test)):
        for i in range(count):
            html, dom, gt, fam = build(i, 9000 + n * 31, split)
            stem = os.path.join(a.out, f"{split}_{i:03d}")
            open(stem + ".html", "w").write(html)
            json.dump({"width": W, "height": H, "family": fam, "split": split,
                       "elements": dom}, open(stem + ".dom.json", "w"), indent=1)
            json.dump({"width": W, "height": H, "family": fam, "split": split,
                       "elements": gt}, open(stem + ".gt.json", "w"), indent=1)
            subprocess.run(["wkhtmltoimage", "--width", str(W), "--height", str(H),
                            "--disable-smart-width", "--quality", "94", stem + ".html",
                            stem + ".png"], check=True, capture_output=True)
            n += 1
    print(f"dev  : {a.dev} pages, families {DEV_FAMILIES}")
    print(f"test : {a.test} pages, families {TEST_FAMILIES}  (never used for tuning)")


if __name__ == "__main__":
    main()
