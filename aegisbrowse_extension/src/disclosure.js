import { coveredBy } from "./coords.js";

const ACTIONABLE = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio"]);

/** Semantic disclosure follows selected element IDs, not merely crop geometry. */
export function buildSafeMetadata(domShot, plan, selection, rebase) {
  const selected = new Set(selection?.selected_ids || []);
  return domShot.elements
    .filter((element) => ACTIONABLE.has(element.role) && element.enabled !== false)
    .filter((element) => selected.has(element.snapshot_id))
    .slice(0, 60)
    .map((element) => {
      const sensitive = plan.some((item) => coveredBy(element.rect, item.box) > 0.35);
      return {
        id: `el_${element.snapshot_id}`,
        role: element.role,
        label: sensitive ? "[REDACTED]" : String(element.label || element.text || "").slice(0, 60),
        rect: rebase ? rebase(element.rect) : element.rect,
        sensitive,
        same_origin: element.same_origin === true,
        options: element.options,
        _shot_rect: element.rect,
      };
    });
}
