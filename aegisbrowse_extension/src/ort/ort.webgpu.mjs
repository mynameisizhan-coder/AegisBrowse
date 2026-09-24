// Load-safe placeholder for the DOM baseline. Replace this file with the real
// onnxruntime-web browser bundle when the trained model is added.
export const env = { wasm: { wasmPaths: "", numThreads: 1 } };
export class Tensor {
  constructor() { throw new Error("ONNX Runtime Web assets are not installed"); }
}
export const InferenceSession = {
  async create() { throw new Error("ONNX Runtime Web assets are not installed"); },
};
