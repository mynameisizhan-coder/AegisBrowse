# AegisBrowse final video recording guide

## Before recording

1. Start `START_AEGISBROWSE_WINDOWS.bat` and leave the terminal visible.
2. Reload AegisBrowse from `chrome://extensions` after replacing the old folder.
3. Pin the extension.
4. Open `http://127.0.0.1:8000/demo`.
5. Use 100% Chrome zoom and close unrelated tabs/notifications.

## 60-second recording

**0–8 seconds — problem.** Show the raw synthetic portal and briefly point to
the name, photograph, PAN, Aadhaar, email and mobile number.

Voice-over: “Cloud browser agents commonly receive the whole screen, including
identity data unrelated to the task.”

**8–18 seconds — task.** Open AegisBrowse, enable **Video evidence mode**, keep
“Download my scholarship certificate,” and press **Run one safe step**.

Voice-over: “AegisBrowse captures the viewport only after user activation and
sanitizes it locally.”

**18–35 seconds — visual privacy proof.** Click **View privacy proof**. Pan from
the Raw panel to Locally sanitized and then Sent to planner. Show the redaction
tokens and the controls-disclosed metric.

Voice-over: “The raw screen never leaves the device. Detected identity fields
and the image region are redacted locally, then the screen is reduced to the
goal-relevant sanitized region. Only one control is disclosed.”

**35–48 seconds — independent server proof.** Open the extension and click
**Server receipt**. Show that the server received the sanitized crop and only
the Download Certificate metadata row.

Voice-over: “This receipt is generated from the actual planner request—not a
mock image. No raw identity value or unrelated control reached the server.”

**48–60 seconds — successful action.** Show the downloaded certificate and the
technical trace fields `gate.verdict: ALLOW`, `stage: VERIFY`, and
`download_started: true`.

Voice-over: “The local safety gate revalidates the target, executes the click,
and verifies the download. AegisBrowse sees less, reveals less, and still
completes the task.”

## Do not claim in the video

Do not say that browser OCR, a face-specific detector, or the trained ONNX
visual detector is complete until those real assets and their held-out results
are bundled. Describe this build as the final **working demo baseline**.
