/** Idempotent, top-frame DOM extractor and stale-target probe. */
(() => {
  if (globalThis.__AEGIS_CONTENT_INSTALLED__) return;
  globalThis.__AEGIS_CONTENT_INSTALLED__ = true;

  const INTERESTING = "input,textarea,select,button,a[href],[role],td,th,p,span,div,img,label";
  const ACTIONABLE_SELECTOR = "input,textarea,select,button,a[href],[role=button],[role=link],[role=textbox],[role=combobox]";

  function clean(value, max = 120) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, max);
  }

  function labelFor(el) {
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label && clean(label.innerText)) return clean(label.innerText);
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return clean(aria);
    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const labels = labelledby.split(/\s+/).map((id) => document.getElementById(id))
        .filter(Boolean).map((node) => clean(node.innerText)).filter(Boolean);
      if (labels.length) return clean(labels.join(" "));
    }
    const wrap = el.closest("label");
    if (wrap && clean(wrap.innerText)) return clean(wrap.innerText);
    if (el.firstElementChild && ["B", "STRONG", "LABEL"].includes(el.firstElementChild.tagName)) {
      const nested = clean(el.firstElementChild.innerText);
      if (nested) return nested;
    }
    const cell = el.closest("td,th");
    if (cell?.previousElementSibling && clean(cell.previousElementSibling.innerText)) {
      return clean(cell.previousElementSibling.innerText);
    }
    if (["BUTTON", "A", "SELECT"].includes(el.tagName) && clean(el.innerText)) return clean(el.innerText);
    const sibling = el.previousElementSibling;
    if (sibling && sibling.children.length === 0 && clean(sibling.innerText)) return clean(sibling.innerText);
    return clean(el.getAttribute("alt") || el.getAttribute("title") || el.getAttribute("placeholder"));
  }

  function visible(el, rect) {
    if (!rect || rect.width < 6 || rect.height < 6) return false;
    if (rect.bottom < 0 || rect.top > innerHeight || rect.right < 0 || rect.left > innerWidth) return false;
    const style = getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none" && style.opacity !== "0";
  }

  function ownText(el) {
    let value = "";
    for (const node of el.childNodes) if (node.nodeType === Node.TEXT_NODE) value += node.nodeValue;
    return clean(value, 600);
  }

  function roleOf(el) {
    const explicit = clean(el.getAttribute("role"));
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "input") {
      const type = (el.type || "text").toLowerCase();
      return type === "checkbox" || type === "radio" ? type : "textbox";
    }
    if (tag === "textarea") return "textbox";
    if (tag === "button") return "button";
    if (tag === "a") return "link";
    if (tag === "img") return "image";
    if (tag === "select") return "combobox";
    return "text";
  }

  function provenance(el) {
    let raw = null;
    if (el instanceof HTMLAnchorElement) raw = el.getAttribute("href");
    else if (el instanceof HTMLButtonElement || el instanceof HTMLInputElement) {
      const form = el.form;
      if (form && (["submit", "image"].includes((el.type || "").toLowerCase()) || el instanceof HTMLButtonElement)) {
        raw = el.getAttribute("formaction") || form.getAttribute("action") || location.href;
      }
    }
    if (!raw) return { same_origin: true, target_origin: location.origin, origin_source: "local-control" };
    try {
      const url = new URL(raw, location.href);
      if (!/^https?:$/.test(url.protocol)) {
        return { same_origin: false, target_origin: url.protocol, origin_source: "non-http-target" };
      }
      return { same_origin: url.origin === location.origin, target_origin: url.origin, origin_source: "resolved-target" };
    } catch {
      return { same_origin: false, target_origin: "invalid", origin_source: "invalid-target" };
    }
  }

  function valueText(el, tag) {
    if (tag === "input" || tag === "textarea") return clean(el.value, 600);
    if (tag === "select") return clean(el.selectedOptions?.[0]?.text || el.value, 600);
    return ownText(el) || (["button", "a"].includes(tag) ? clean(el.innerText, 600) : "");
  }

  function record(el, index) {
    const rectObject = el.getBoundingClientRect();
    if (!visible(el, rectObject)) return null;
    const tag = el.tagName.toLowerCase();
    const text = valueText(el, tag);
    const isControl = ["input", "button", "select", "textarea", "a", "img"].includes(tag) || el.hasAttribute("role");
    if (!isControl && (!text || text.length > 600)) return null;
    const rect = [Math.round(rectObject.left), Math.round(rectObject.top),
                  Math.round(rectObject.right), Math.round(rectObject.bottom)];
    const rec = { snapshot_id: index, tag, role: roleOf(el), rect, text, label: labelFor(el), ...provenance(el) };
    if (tag === "input" || tag === "textarea") {
      const type = tag === "textarea" ? "text" : (el.type || "text").toLowerCase();
      rec.input_type = type;
      rec.autocomplete = el.getAttribute("autocomplete") || "";
      rec.inputmode = el.getAttribute("inputmode") || "";
      rec.maxlength = el.getAttribute("maxlength") || "";
      if (type !== "password" && (/one-time-code/i.test(rec.autocomplete) || /otp|one[\s-]?time/i.test(rec.label) ||
          (rec.inputmode === "numeric" && rec.maxlength === "6"))) rec.input_type = "otp";
    }
    if (tag === "select") rec.options = [...el.options].slice(0, 40).map((option) => clean(option.text || option.value, 80));
    rec.enabled = !(el.disabled || el.getAttribute("aria-disabled") === "true");
    return rec;
  }

  function snapshot() {
    const elements = [], seen = new Set();
    let index = 0;
    for (const el of document.querySelectorAll(INTERESTING)) {
      const rec = record(el, index++);
      if (!rec) continue;
      const key = `${rec.tag}|${rec.rect.join(",")}|${rec.text.slice(0,40)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      elements.push(rec);
    }
    return { url_origin: location.origin, url: location.href, width: innerWidth, height: innerHeight,
             dpr: devicePixelRatio, captured_at: Date.now(), elements };
  }

  function probe(rect, expect = {}) {
    const x = (rect[0] + rect[2]) / 2, y = (rect[1] + rect[3]) / 2;
    let el = document.elementFromPoint(x, y);
    if (!el) return { ok: false, reason: "no element at target point" };
    el = el.closest(ACTIONABLE_SELECTOR) || el;
    const current = record(el, -1);
    if (!current) return { ok: false, reason: "target is hidden" };
    if (!current.enabled) return { ok: false, reason: "target is disabled" };
    if (expect.role && current.role !== expect.role) return { ok: false, reason: "target role changed", current };
    const expectedLabel = clean(expect.label).toLowerCase(), actualLabel = clean(current.label || current.text).toLowerCase();
    if (expectedLabel && !(actualLabel.includes(expectedLabel) || expectedLabel.includes(actualLabel))) {
      return { ok: false, reason: "target label changed", current };
    }
    if (expect.same_origin !== undefined && current.same_origin !== expect.same_origin) {
      return { ok: false, reason: "target origin changed", current };
    }
    return { ok: true, probe: current };
  }

  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    try {
      if (message?.type === "AEGIS_SNAPSHOT") respond({ ok: true, dom: snapshot() });
      else if (message?.type === "AEGIS_PROBE") respond(probe(message.rect, message.expect));
    } catch (error) {
      respond({ ok: false, error: String(error?.message || error) });
    }
    return true;
  });
})();
