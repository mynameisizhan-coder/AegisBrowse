# Optional learned detector

The end-to-end demo runs safely with the DOM perception fallback. To enable the
learned visual path, place the team's trained YOLO-style ONNX model here as
`ui_detector.onnx`. Its output must be `[1, 4 + 5, anchors]` with class order:

`button, input, value_chip, status_block, image_region`.

Do not substitute an untrained/dummy model; the UI accuracy result must come
from the held-out benchmark.
