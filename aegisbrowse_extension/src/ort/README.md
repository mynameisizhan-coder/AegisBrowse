# Optional ONNX Runtime Web assets

The base prototype deliberately lazy-loads ONNX Runtime so missing optional
assets cannot prevent the extension from loading. For the learned-model build,
copy the browser distribution from `onnxruntime-web` into this folder, replacing
the load-safe placeholder `ort.webgpu.mjs` and adding its referenced WASM files.
No runtime code is fetched from a CDN. A local placeholder is included because
Chrome extension service workers require a resolvable static module graph.
