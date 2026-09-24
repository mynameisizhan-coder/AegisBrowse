/** AegisBrowse MV3 loop: observe → sanitize → minimize → plan → gate → execute → verify. */
import { detectUI, memorySample, coldStartInfo } from "./perception.js";
import { buildPlan, applyRedaction, sanitizeGoal } from "./privacy.js";
import { makeMapper } from "./coords.js";
import { selectContext, applyCrop } from "./roi.js";
import { buildSafeMetadata } from "./disclosure.js";

const IMPLEMENTED = new Set(["CLICK", "TYPE", "SCROLL", "SELECT", "WAIT", "STOP"]);
const RISK = { SCROLL: "R0", WAIT: "R0", STOP: "R0", SELECT: "R1", CLICK: "R1", TYPE: "R2" };
const NEEDS_TARGET = new Set(["CLICK", "TYPE", "SELECT"]);
const ACTIONABLE = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio"]);
const PENDING_KEY = "aegis_pending_action";
const PROOF_KEY = "aegis_last_privacy_proof";
const CONFIRM_TTL_MS = 2 * 60 * 1000;
const PROOF_TTL_MS = 10 * 60 * 1000;
let lastCaptureAt = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const elapsed = (start) => Math.round(performance.now() - start);

async function ensureExtractor(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["src/content_dom.js"] });
}

async function observe(tab) {
  const started = performance.now();
  await ensureExtractor(tab.id);
  const response = await chrome.tabs.sendMessage(tab.id, { type: "AEGIS_SNAPSHOT" });
  if (!response?.ok) throw new Error(`DOM snapshot failed: ${response?.error || "no response"}`);
  const wait = Math.max(0, 550 - (Date.now() - lastCaptureAt));
  if (wait) await sleep(wait); // captureVisibleTab is limited to two calls/second
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
  lastCaptureAt = Date.now();
  const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob());
  return { dom: response.dom, bitmap, capture_ms: elapsed(started) };
}

async function perceiveAndSanitize({ dom, bitmap }, goal) {
  const map = makeMapper(dom, bitmap);
  const elements = dom.elements.map((element) => ({ ...element, rect: map.toShot(element.rect) }));
  const domShot = { ...dom, elements };
  const heapBefore = memorySample();
  let detections = [], perception = null, provider = "dom-fallback";
  try {
    const result = await detectUI(bitmap);
    detections = result.detections;
    perception = result.timing;
    provider = result.provider;
  } catch (error) {
    console.info("[AegisBrowse] optional ONNX detector unavailable; using DOM fallback", error?.message);
  }

  const planStart = performance.now();
  const plan = buildPlan(domShot, detections);
  const planMs = elapsed(planStart);
  const redactStart = performance.now();
  const { bitmap: safeBitmap, tokens } = await applyRedaction(bitmap, plan);
  const redactMs = elapsed(redactStart);
  const selectStart = performance.now();
  const selection = selectContext(goal, elements, detections, plan,
    { width: bitmap.width, height: bitmap.height });
  const cropped = selection.mode === "full-view" ? null : await applyCrop(safeBitmap, selection.crop);
  const selectMs = elapsed(selectStart);
  return {
    map, domShot, plan, tokens, selection, cropped, safeBitmap,
    outBitmap: cropped?.bitmap || safeBitmap,
    telemetry: {
      coordinate_space: map.describe(), provider, perception,
      cold_start: coldStartInfo(), pii_plan_ms: planMs, redaction_ms: redactMs,
      context_select_ms: selectMs, detections: detections.length, redactions: plan.length,
      context: { mode: selection.mode, reason: selection.reason,
                 pixel_fraction: selection.pixel_fraction ?? 1 },
      memory_before: heapBefore, memory_after: memorySample(),
    },
  };
}

export const safeMetadata = buildSafeMetadata;

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  }
  return btoa(binary);
}

async function previewDataUrl(bitmap, maxWidth = 960) {
  const scale=Math.min(1,maxWidth/bitmap.width);
  const width=Math.max(1,Math.round(bitmap.width*scale));
  const height=Math.max(1,Math.round(bitmap.height*scale));
  const canvas=new OffscreenCanvas(width,height);
  canvas.getContext("2d").drawImage(bitmap,0,0,width,height);
  const blob=await canvas.convertToBlob({type:"image/webp",quality:0.72});
  return `data:image/webp;base64,${bytesToBase64(await blob.arrayBuffer())}`;
}

async function savePrivacyProof({ goal, observed, sanitized, metadata, planned, stage }) {
  const createdAt=Date.now();
  const [raw,safe,sent]=await Promise.all([
    previewDataUrl(observed.bitmap), previewDataUrl(sanitized.safeBitmap), previewDataUrl(sanitized.outBitmap),
  ]);
  const safeMetadata=metadata.map(({_shot_rect,...item})=>item);
  const context=sanitized.telemetry.context || {};
  const proof={
    schema:"aegisbrowse-proof-v1",created_at:createdAt,expires_at:createdAt+PROOF_TTL_MS,
    goal,sanitized_goal:planned?.goal_privacy?.sanitized || sanitizeGoal(goal).sanitized,stage,
    images:{raw,sanitized:safe,sent},
    tokens:sanitized.tokens.map(({token,cls,layer})=>({token,cls,layer})),
    safe_metadata:safeMetadata,
    action:planned?.action || null,
    metrics:{pixel_fraction:context.pixel_fraction ?? 1,
      element_fraction:sanitized.all_controls?metadata.length/sanitized.all_controls:0,
      disclosed_elements:metadata.length,observed_controls:sanitized.all_controls || 0,
      request_bytes:planned?.payload?.request_bytes || 0,provider:sanitized.telemetry.provider},
  };
  await chrome.storage.session.set({[PROOF_KEY]:proof});
  await chrome.alarms.create("aegis-proof-expire",{when:proof.expires_at});
  return true;
}

function validatedEndpoint(value) {
  const url = new URL(value);
  const local = (url.hostname === "127.0.0.1" || url.hostname === "localhost") && url.protocol === "http:";
  if (!local || url.port !== "8000" || url.pathname !== "/plan") {
    throw new Error("Prototype planner must be http://127.0.0.1:8000/plan");
  }
  return url.href;
}

async function callPlanner(originalGoal, bitmap, metadata, endpoint) {
  const goalPrivacy = sanitizeGoal(originalGoal);
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  canvas.getContext("2d").drawImage(bitmap, 0, 0);
  const png = await canvas.convertToBlob({ type: "image/png" });
  const base64 = bytesToBase64(await png.arrayBuffer());
  const wire = metadata.map(({ _shot_rect, ...safe }) => safe);
  const body = JSON.stringify({ goal: goalPrivacy.sanitized, safe_metadata: wire, visual_context: base64 });
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  const started = performance.now();
  try {
    const response = await fetch(validatedEndpoint(endpoint), {
      method: "POST", headers: { "Content-Type": "application/json" }, body, signal: controller.signal,
    });
    if (!response.ok) throw new Error(`planner HTTP ${response.status}: ${(await response.text()).slice(0, 160)}`);
    return {
      action: await response.json(), network_ms: elapsed(started), goal_privacy: goalPrivacy,
      payload: { png_bytes: png.size, base64_bytes: new TextEncoder().encode(base64).length,
        metadata_bytes: new TextEncoder().encode(JSON.stringify(wire)).length,
        request_bytes: new TextEncoder().encode(body).length },
    };
  } finally {
    clearTimeout(timeout);
  }
}

const STOP_WORDS = new Set(["the","a","an","my","our","for","to","of","in","on","and","or",
  "please","can","you","i","me","with","from","this","that"]);
const terms = (value) => String(value || "").toLowerCase().split(/[^a-z0-9]+/)
  .filter((term) => term.length > 2 && !STOP_WORDS.has(term));

export function intentAligned(goal, target) {
  const requested = terms(goal), targetTerms = terms(`${target?.label || ""} ${target?.role || ""}`);
  if (!requested.length) return { ok: false, note: "goal has no actionable terms" };
  if (!targetTerms.length) return { ok: false, note: "target has no safe label" };
  const hit = requested.some((x) => targetTerms.some((y) => x === y || x.startsWith(y) || y.startsWith(x)));
  return { ok: hit, note: hit ? "goal term matches target label" : "no goal term matches target label" };
}

export function validate(action, metadata, goal) {
  const block = (reason) => ({ verdict: "BLOCK", reason });
  if (!action || typeof action !== "object") return block("planner returned no object");
  if (!IMPLEMENTED.has(action.action)) return block(`unsupported action: ${action.action}`);
  if (!NEEDS_TARGET.has(action.action)) return { verdict: "ALLOW", reason: `${action.action} needs no target`, target: null };
  const target = metadata.find((item) => item.id === action.target_id);
  if (!target) return block("target_id is outside disclosed metadata");
  if (target.sensitive) return block("target overlaps a redacted region");
  if (!target.same_origin) return block("target origin is cross-origin or unresolved");
  const intent = intentAligned(goal, target);
  if (!intent.ok) return block(`intent check: ${intent.note}`);
  const tier = RISK[action.action];
  return tier === "R2"
    ? { verdict: "CONFIRM", reason: "state-changing input action", target, tier, intent: intent.note }
    : { verdict: "ALLOW", reason: `risk ${tier}`, target, tier, intent: intent.note };
}

async function revalidate(tabId, target, cssRect) {
  const response = await chrome.tabs.sendMessage(tabId, { type: "AEGIS_PROBE", rect: cssRect,
    expect: { role: target.role, label: target.label === "[REDACTED]" ? "" : target.label,
              same_origin: target.same_origin } });
  return response?.ok ? { ...response.probe, ok: true, cssRect }
    : { ok: false, reason: response?.reason || response?.error || "probe failed", cssRect };
}

async function execute(tabId, action, cssRect) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, args: [action, cssRect],
    func: (act, rect) => {
      const before = { url: location.href, title: document.title, height: document.body.scrollHeight,
        scroll_y: scrollY, text_length: document.body.innerText.length };
      try {
        if (act.action === "SCROLL") {
          scrollBy({ top: Number(act.value) || 400, behavior: "instant" });
          return { ok: true, before };
        }
        const x=(rect[0]+rect[2])/2, y=(rect[1]+rect[3])/2;
        let element=document.elementFromPoint(x,y);
        element=element?.closest("input,textarea,select,button,a[href],[role=button],[role=link],[role=textbox],[role=combobox]") || element;
        if (!element) return { ok: false, error: "no actionable element at target point", before };
        if (element.disabled || element.getAttribute("aria-disabled") === "true") return { ok: false, error: "target is disabled", before };
        if (act.action === "CLICK") {
          element.focus(); element.click();
        } else if (act.action === "TYPE") {
          if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)) return { ok:false,error:"target is not a text field",before };
          const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
          element.focus();
          if (setter) setter.call(element, String(act.value ?? "")); else element.value = String(act.value ?? "");
          element.dispatchEvent(new InputEvent("input", { bubbles:true, inputType:"insertText", data:String(act.value ?? "") }));
          element.dispatchEvent(new Event("change", { bubbles:true }));
          if (element.value !== String(act.value ?? "")) return { ok:false,error:"framework rejected value",before };
        } else if (act.action === "SELECT") {
          const select = element instanceof HTMLSelectElement ? element : element.closest("select");
          if (!select) return { ok:false,error:"target is not a select",before };
          const wanted=String(act.value ?? "").toLowerCase();
          const option=[...select.options].find((item)=>item.value.toLowerCase()===wanted || item.text.trim().toLowerCase()===wanted);
          if (!option) return { ok:false,error:`option not found: ${act.value}`,before };
          const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value")?.set;
          if (setter) setter.call(select,option.value); else select.value=option.value;
          select.dispatchEvent(new Event("input",{bubbles:true}));
          select.dispatchEvent(new Event("change",{bubbles:true}));
        }
        return { ok:true,before };
      } catch (error) { return { ok:false,error:String(error?.message || error),before }; }
    } });
  return result;
}

function watchDownloads(windowMs = 3500) {
  return new Promise((resolve) => {
    const downloads=[];
    const listener=(item)=>downloads.push({ id:item.id, filename:item.filename, mime:item.mime });
    chrome.downloads.onCreated.addListener(listener);
    setTimeout(()=>{ chrome.downloads.onCreated.removeListener(listener); resolve(downloads); }, windowMs);
  });
}

async function verify(tabId, before, downloadPromise) {
  await sleep(700);
  const downloads = await downloadPromise;
  let after = null;
  try {
    [{ result: after }] = await chrome.scripting.executeScript({ target:{tabId}, func:()=>({
      url:location.href,title:document.title,height:document.body.scrollHeight,
      scroll_y:scrollY,text_length:document.body.innerText.length,
    }) });
  } catch { /* a navigation can destroy the previous execution context */ }
  const signals = { download_started: downloads.length > 0, navigated: !after || after.url !== before.url,
    title_changed: !!after && after.title !== before.title,
    dom_changed: !!after && (after.height !== before.height || Math.abs(after.text_length-before.text_length) > 5),
    scrolled: !!after && after.scroll_y !== before.scroll_y };
  return { changed:Object.values(signals).some(Boolean),signals,downloads,before,after };
}

async function savePending(data) { await chrome.storage.session.set({ [PENDING_KEY]: data }); }
async function takePending(token, activeTab) {
  const pending=(await chrome.storage.session.get(PENDING_KEY))[PENDING_KEY];
  if (!pending || pending.token !== token) throw new Error("confirmation token expired or invalid");
  if (Date.now()-pending.created_at > CONFIRM_TTL_MS) throw new Error("confirmation expired");
  if (activeTab.id !== pending.tab_id) throw new Error("confirmation belongs to a different tab");
  if (new URL(activeTab.url).origin !== pending.origin) throw new Error("tab origin changed after confirmation request");
  await chrome.storage.session.remove(PENDING_KEY);
  return pending;
}

async function activeHttpTab() {
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if (!tab?.id || !/^https?:/.test(tab.url || "")) throw new Error("Open an http(s) page before running AegisBrowse");
  return tab;
}

async function step(goal, endpoint, confirmToken, evidenceMode = false) {
  const tab=await activeHttpTab();
  const started=performance.now();
  if (confirmToken) {
    const pending=await takePending(confirmToken,tab);
    const probe=await revalidate(tab.id,pending.target,pending.css_rect);
    if (!probe.ok) return {...pending.trace,stage:"STALE",probe,telemetry:{...pending.trace.telemetry,total_ms:elapsed(started)}};
    const downloads=watchDownloads();
    const executed=await execute(tab.id,pending.action,pending.css_rect);
    if (!executed?.ok) return {...pending.trace,stage:"EXECUTE",error:executed?.error};
    return {...pending.trace,stage:"VERIFY",confirmed:true,
      verification:await verify(tab.id,executed.before,downloads),
      telemetry:{...pending.trace.telemetry,total_ms:elapsed(started)}};
  }

  const observed=await observe(tab);
  const sanitized=await perceiveAndSanitize(observed,goal);
  const metadata=safeMetadata(sanitized.domShot,sanitized.plan,sanitized.selection,sanitized.cropped?.rebase);
  const allControls=sanitized.domShot.elements.filter((element)=>ACTIONABLE.has(element.role)).length;
  sanitized.all_controls=allControls;
  const trace={ telemetry:{...sanitized.telemetry,capture_ms:observed.capture_ms,
      context:{...sanitized.telemetry.context,element_fraction:allControls?+(metadata.length/allControls).toFixed(3):0}},
    tokens:sanitized.tokens.map(({token,cls,layer})=>({token,cls,layer})),
    context:sanitized.selection,disclosed_elements:metadata.length,observed_controls:allControls };
  if (!endpoint) {
    if (evidenceMode) {
      try {
        await savePrivacyProof({goal,observed,sanitized,metadata,planned:null,stage:"SANITIZE — NO NETWORK"});
        trace.proof_ready=true;
      } catch (error) { trace.proof_error=String(error?.message || error); }
    }
    return {...trace,stage:"SANITIZE",note:"stopped before network by user choice",
      telemetry:{...trace.telemetry,total_ms:elapsed(started)}};
  }

  const planned=await callPlanner(goal,sanitized.outBitmap,metadata,endpoint);
  trace.telemetry.network_ms=planned.network_ms;
  trace.telemetry.payload=planned.payload;
  trace.goal_privacy={ sanitized:planned.goal_privacy.sanitized, redactions:planned.goal_privacy.mappings.length };
  trace.action=planned.action;
  if (evidenceMode) {
    try {
      await savePrivacyProof({goal,observed,sanitized,metadata,planned,stage:"PLANNED — SANITIZED ONLY"});
      trace.proof_ready=true;
    } catch (error) { trace.proof_error=String(error?.message || error); }
  }
  const gate=validate(planned.action,metadata,goal);
  trace.gate=gate;
  if (gate.verdict === "BLOCK") return {...trace,stage:"VALIDATE",telemetry:{...trace.telemetry,total_ms:elapsed(started)}};
  if (gate.verdict === "CONFIRM") {
    const token=crypto.randomUUID();
    const cssRect=sanitized.map.toCss(gate.target._shot_rect);
    await savePending({ token,tab_id:tab.id,origin:new URL(tab.url).origin,action:planned.action,
      target:gate.target,css_rect:cssRect,created_at:Date.now(),trace });
    return {...trace,stage:"CONFIRM",confirm_token:token,prompt:`Allow ${planned.action.action} on “${gate.target.label}”?`,
      telemetry:{...trace.telemetry,total_ms:elapsed(started)}};
  }
  if (planned.action.action === "STOP") return {...trace,stage:"DONE",note:"planner signalled task complete",
    telemetry:{...trace.telemetry,total_ms:elapsed(started)}};
  if (planned.action.action === "WAIT") {
    await sleep(Math.min(5000,Math.max(100,Number(planned.action.value)||1000)));
    return {...trace,stage:"WAIT",note:"waited locally; run the next observation step",
      telemetry:{...trace.telemetry,total_ms:elapsed(started)}};
  }
  if (planned.action.action === "SCROLL") {
    const executed=await execute(tab.id,planned.action,[0,0,0,0]);
    return {...trace,stage:"VERIFY",verification:await verify(tab.id,executed.before,Promise.resolve([])),
      telemetry:{...trace.telemetry,total_ms:elapsed(started)}};
  }
  const cssRect=sanitized.map.toCss(gate.target._shot_rect);
  const probe=await revalidate(tab.id,gate.target,cssRect);
  if (!probe.ok) return {...trace,stage:"STALE",probe,note:"target changed since planning"};
  const downloads=watchDownloads();
  const executed=await execute(tab.id,planned.action,cssRect);
  if (!executed?.ok) return {...trace,stage:"EXECUTE",error:executed?.error};
  return {...trace,stage:"VERIFY",verification:await verify(tab.id,executed.before,downloads),
    telemetry:{...trace.telemetry,total_ms:elapsed(started)}};
}

chrome.runtime.onMessage.addListener((message,_sender,respond)=>{
  if (message?.type === "AEGIS_STEP") {
    step(message.goal,message.endpoint,message.confirmToken,message.evidenceMode === true)
      .then((result)=>respond({ok:true,result}))
      .catch((error)=>respond({ok:false,error:String(error?.message || error)}));
    return true;
  }
  if (message?.type === "AEGIS_DENY") {
    chrome.storage.session.get(PENDING_KEY).then((stored)=>{
      if (stored[PENDING_KEY]?.token === message.confirmToken) return chrome.storage.session.remove(PENDING_KEY);
    }).then(()=>respond({ok:true}));
    return true;
  }
});

chrome.alarms.onAlarm.addListener((alarm)=>{
  if (alarm.name === "aegis-proof-expire") chrome.storage.session.remove(PROOF_KEY);
});
