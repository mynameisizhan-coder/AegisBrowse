/** Optional on-device ONNX perception. The extension remains loadable without M1 assets. */
import * as ort from "./ort/ort.webgpu.mjs";

const MODEL_PATH = "models/ui_detector.onnx";
const INPUT_SIZE = 640;
const CONF_THRESHOLD = 0.30;
const IOU_THRESHOLD = 0.45;

export const CLASSES = ["button", "input", "value_chip", "status_block", "image_region"];

let sessionPromise = null;
let activeProvider = "dom-fallback";
let cold = { attempted: false, available: false, load_ms: null, error: null };

ort.env.wasm.wasmPaths = chrome.runtime.getURL("src/ort/");
ort.env.wasm.numThreads = Math.max(1, Math.min(4, navigator.hardwareConcurrency || 2));

export async function getSession() {
  if (sessionPromise) return sessionPromise;
  sessionPromise = (async () => {
    const started = performance.now();
    cold = { attempted: true, available: false, load_ms: null, error: null };
    try {
      const modelResponse = await fetch(chrome.runtime.getURL(MODEL_PATH));
      if (!modelResponse.ok) throw new Error(`model missing (${modelResponse.status})`);
      const model = await modelResponse.arrayBuffer();
      for (const ep of ["webgpu", "wasm"]) {
        try {
          const session = await ort.InferenceSession.create(model, {
            executionProviders: [ep], graphOptimizationLevel: "all",
          });
          activeProvider = ep;
          cold = { attempted: true, available: true,
                   load_ms: Math.round(performance.now() - started), error: null };
          return { ort, session };
        } catch (error) {
          cold.error = `${ep}: ${String(error?.message || error)}`;
        }
      }
      throw new Error(cold.error || "no usable ONNX execution provider");
    } catch (error) {
      activeProvider = "dom-fallback";
      cold = { attempted: true, available: false,
               load_ms: Math.round(performance.now() - started),
               error: String(error?.message || error) };
      sessionPromise = null;
      throw error;
    }
  })();
  return sessionPromise;
}

export function provider() { return activeProvider; }
export function coldStartInfo() { return { ...cold, provider: activeProvider }; }

function preprocess(bitmap, ort) {
  const scale = Math.min(INPUT_SIZE / bitmap.width, INPUT_SIZE / bitmap.height);
  const nw = Math.round(bitmap.width * scale), nh = Math.round(bitmap.height * scale);
  const dx = Math.floor((INPUT_SIZE - nw) / 2), dy = Math.floor((INPUT_SIZE - nh) / 2);
  const canvas = new OffscreenCanvas(INPUT_SIZE, INPUT_SIZE);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#727272";
  ctx.fillRect(0, 0, INPUT_SIZE, INPUT_SIZE);
  ctx.drawImage(bitmap, 0, 0, bitmap.width, bitmap.height, dx, dy, nw, nh);
  const { data } = ctx.getImageData(0, 0, INPUT_SIZE, INPUT_SIZE);
  const pixels = INPUT_SIZE * INPUT_SIZE;
  const chw = new Float32Array(3 * pixels);
  for (let i = 0; i < pixels; i++) {
    chw[i] = data[i * 4] / 255;
    chw[pixels + i] = data[i * 4 + 1] / 255;
    chw[2 * pixels + i] = data[i * 4 + 2] / 255;
  }
  return { tensor: new ort.Tensor("float32", chw, [1, 3, INPUT_SIZE, INPUT_SIZE]), scale, dx, dy };
}

function iou(a, b) {
  const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[2], b[2]), y2 = Math.min(a[3], b[3]);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter;
  return union > 0 ? inter / union : 0;
}

function decode(output, meta, width, height) {
  if (!output?.dims || output.dims.length !== 3) throw new Error("unsupported detector output shape");
  const [, channels, anchors] = output.dims;
  if (channels < 5) throw new Error("detector output has no class channels");
  const data = output.data, classCount = channels - 4, detections = [];
  for (let i = 0; i < anchors; i++) {
    let score = 0, classIndex = -1;
    for (let c = 0; c < classCount; c++) {
      const candidate = data[(4 + c) * anchors + i];
      if (candidate > score) { score = candidate; classIndex = c; }
    }
    if (score < CONF_THRESHOLD) continue;
    const cx=data[i], cy=data[anchors+i], w=data[2*anchors+i], h=data[3*anchors+i];
    const box = [
      (cx-w/2-meta.dx)/meta.scale, (cy-h/2-meta.dy)/meta.scale,
      (cx+w/2-meta.dx)/meta.scale, (cy+h/2-meta.dy)/meta.scale,
    ];
    box[0]=Math.max(0,Math.min(width,box[0])); box[2]=Math.max(0,Math.min(width,box[2]));
    box[1]=Math.max(0,Math.min(height,box[1])); box[3]=Math.max(0,Math.min(height,box[3]));
    if (box[2]-box[0] < 4 || box[3]-box[1] < 4) continue;
    detections.push({ cls: CLASSES[classIndex] || `class_${classIndex}`,
      box: box.map(Math.round), score: +score.toFixed(3) });
  }
  const kept=[];
  for (const item of detections.sort((a,b)=>b.score-a.score)) {
    if (kept.every((other)=>other.cls!==item.cls || iou(other.box,item.box)<IOU_THRESHOLD)) kept.push(item);
  }
  return kept;
}

export async function detectUI(bitmap) {
  const { ort, session } = await getSession();
  const prepStart = performance.now();
  const meta = preprocess(bitmap, ort);
  const preprocess_ms = performance.now() - prepStart;
  const inferenceStart = performance.now();
  const outputMap = await session.run({ [session.inputNames[0]]: meta.tensor });
  const inference_ms = performance.now() - inferenceStart;
  const decodeStart = performance.now();
  const detections = decode(outputMap[session.outputNames[0]], meta, bitmap.width, bitmap.height);
  const decode_ms = performance.now() - decodeStart;
  return { detections,
    timing: { preprocess_ms: Math.round(preprocess_ms), inference_ms: Math.round(inference_ms),
              decode_ms: Math.round(decode_ms), warm_total_ms: Math.round(preprocess_ms+inference_ms+decode_ms) },
    cold: coldStartInfo(), provider: activeProvider };
}

export function memorySample() {
  const heap = performance.memory?.usedJSHeapSize;
  return { js_heap_mb: heap ? +(heap / 1048576).toFixed(1) : null,
           note: "JS heap only; use Chrome Task Manager for total extension/GPU memory" };
}
