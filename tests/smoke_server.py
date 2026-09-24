#!/usr/bin/env python3
import base64
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nsynthetic").decode()


def request(path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, response.read(), response.headers


status, body, _ = request("/health")
assert status == 200 and json.loads(body)["ok"] is True

status, body, _ = request("/")
assert status == 200 and b"National Scholarship Portal" in body

status, body, _ = request("/plan", {
    "goal": "Download my scholarship certificate for [PAN_1]",
    "safe_metadata": [
        {"id":"el_1","role":"link","label":"Download Certificate","rect":[0,0,100,40],"same_origin":True},
        {"id":"el_2","role":"button","label":"Print","rect":[120,0,180,40],"same_origin":True},
    ],
    "visual_context": PNG,
})
planned = json.loads(body)
assert status == 200 and planned["action"] == "CLICK" and planned["target_id"] == "el_1"

status, body, _ = request("/inspector/data")
receipt = json.loads(body)
assert status == 200 and receipt["available"] is True
assert receipt["goal"].endswith("[PAN_1]") and "ABCDE1234F" not in json.dumps(receipt)
assert receipt["image_bytes"] == len(base64.b64decode(PNG))

status, body, _ = request("/inspector")
assert status == 200 and b"What the server actually received" in body

try:
    request("/plan", {"goal":"download certificate","safe_metadata":[],"visual_context":"%%%bad%%%"})
    raise AssertionError("malformed Base64 was accepted")
except urllib.error.HTTPError as error:
    assert error.code == 422

status, body, headers = request("/demo/certificate")
assert status == 200 and b"synthetic scholarship certificate" in body
assert "attachment" in headers.get("Content-Disposition", "")
print("server-smoke: health, planner, receipt, Base64 rejection and download passed")
