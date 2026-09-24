const $ = (id) => document.getElementById(id);
let confirmToken = null;

function setStatus(title, detail, tone = "idle") {
  $("status").className = `status ${tone}`;
  $("status").innerHTML = "";
  const strong = document.createElement("strong");
  const span = document.createElement("span");
  strong.textContent = title;
  span.textContent = detail;
  $("status").append(strong, span);
}

function showTrace(value) {
  $("trace").textContent = JSON.stringify(value, null, 2);
}

async function runStep(token = null) {
  const goal = $("goal").value.trim();
  const endpoint = $("endpoint").value.trim();
  if (!goal) return setStatus("Task required", "Describe one browser action.", "bad");

  $("run").disabled = true;
  $("confirm").classList.add("hidden");
  setStatus("Running locally…", "Capturing, detecting and redacting before planning.");
  await chrome.storage.local.set({ goal, endpoint });

  try {
    const response = await chrome.runtime.sendMessage({
      type: "AEGIS_STEP", goal, endpoint, confirmToken: token,
      evidenceMode: $("evidence").checked,
    });
    if (!response?.ok) throw new Error(response?.error || "No response from service worker");
    const r = response.result;
    showTrace(r);

    if (r.proof_ready) $("proof").classList.add("ready");
    if (r.stage === "CONFIRM") {
      confirmToken = r.confirm_token;
      $("confirmText").textContent = r.prompt;
      $("confirm").classList.remove("hidden");
      setStatus("Paused at safety gate", "The action will not run without your approval.", "warn");
    } else if (["VERIFY", "DONE", "SANITIZE", "WAIT"].includes(r.stage)) {
      const verified = r.verification?.changed;
      setStatus(
        verified === false ? "Action ran; no postcondition detected" : `Stage: ${r.stage}`,
        r.note || (verified ? "Verified by a local post-action signal." : "See the technical trace."),
        verified === false ? "warn" : "good",
      );
    } else {
      setStatus(`Stopped at ${r.stage}`, r.error || r.gate?.reason || r.note || "Safety check stopped the action.", "bad");
    }
  } catch (error) {
    setStatus("Prototype error", String(error.message || error), "bad");
    showTrace({ error: String(error.stack || error) });
  } finally {
    $("run").disabled = false;
  }
}

$("run").addEventListener("click", () => runStep());
$("allow").addEventListener("click", () => runStep(confirmToken));
$("deny").addEventListener("click", async () => {
  if (confirmToken) await chrome.runtime.sendMessage({ type: "AEGIS_DENY", confirmToken });
  confirmToken = null;
  $("confirm").classList.add("hidden");
  setStatus("Denied", "The pending action was deleted.", "good");
});
$("demo").addEventListener("click", () => chrome.tabs.create({ url: "http://127.0.0.1:8000/demo" }));
$("proof").addEventListener("click", () => chrome.tabs.create({ url: chrome.runtime.getURL("src/proof.html") }));
$("serverProof").addEventListener("click", () => chrome.tabs.create({ url: "http://127.0.0.1:8000/inspector" }));
$("evidence").addEventListener("change", () => chrome.storage.local.set({ evidenceMode: $("evidence").checked }));

chrome.storage.local.get(["goal", "endpoint", "evidenceMode"]).then((saved) => {
  if (saved.goal) $("goal").value = saved.goal;
  if (saved.endpoint) $("endpoint").value = saved.endpoint;
  $("evidence").checked = saved.evidenceMode === true;
});
