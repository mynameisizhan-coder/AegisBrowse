import assert from "node:assert/strict";
import { makeMapper, coveredBy } from "../aegisbrowse_extension/src/coords.js";
import { selectContext } from "../aegisbrowse_extension/src/roi.js";
import { buildPlan, classifyText, sanitizeGoal } from "../aegisbrowse_extension/src/privacy.js";
import { buildSafeMetadata } from "../aegisbrowse_extension/src/disclosure.js";

const elements = [
  { snapshot_id: 1, role: "button", rect: [50,400,230,450], label: "Download Certificate", text: "" },
  { snapshot_id: 2, role: "button", rect: [250,400,330,450], label: "Print", text: "" },
  { snapshot_id: 3, role: "link", rect: [350,400,430,450], label: "Help", text: "" },
  { snapshot_id: 4, role: "text", rect: [50,350,400,385], label: "", text: "Scholarship Status" },
];
const selection = selectContext("Download my scholarship certificate", elements, [], [], { width: 1000, height: 700 });
assert.equal(selection.mode, "task-roi");
assert(selection.selected_ids.includes(1), "goal-matching Download control must survive");
assert(!selection.selected_ids.includes(2), "actionability alone must not retain Print");
assert(!selection.selected_ids.includes(3), "actionability alone must not retain Help");
assert(coveredBy(elements[0].rect, selection.crop) > 0.99);
const metadata = buildSafeMetadata({ elements: elements.map((element) => ({ ...element, enabled:true, same_origin:true })) }, [], selection);
assert.deepEqual(metadata.map((item) => item.label), ["Download Certificate"]);

const empty = selectContext("Reconcile the moon ledger", elements, [], [], { width: 1000, height: 700 });
assert.equal(empty.mode, "minimal-empty");
assert.equal(empty.kept, 0);

const mapper = makeMapper({ width: 1000, height: 700, dpr: 2 }, { width: 2000, height: 1400 });
assert.deepEqual(mapper.toShot([10,20,30,40]), [20,40,60,80]);
assert.deepEqual(mapper.toCss([20,40,60,80]), [10,20,30,40]);

assert.equal(classifyText("ABCDE1234F", "PAN"), "PAN");
assert.equal(classifyText("student@example.in", "Email"), "EMAIL");
assert.equal(classifyText("2345 6789 0123", "Aadhaar"), "AADHAAR");
const goal = sanitizeGoal("Enter PAN ABCDE1234F and email student@example.in");
assert(!goal.sanitized.includes("ABCDE1234F"));
assert(!goal.sanitized.includes("student@example.in"));
assert(goal.sanitized.includes("[PAN_1]"));
assert(goal.sanitized.includes("[EMAIL_1]"));

const plan = buildPlan({ elements: [
  { role:"text", rect:[0,0,100,30], text:"ABCDE1234F", label:"PAN" },
  { role:"image", rect:[0,40,100,140], text:"", label:"Applicant photograph" },
]}, []);
assert(plan.some((item) => item.cls === "PAN"));
assert(plan.some((item) => item.cls === "IMAGE_REGION" && item.mode === "blur"));
console.log("core-js: 17 assertions passed");
