const KEY = "aegis_last_privacy_proof";
const $ = (id) => document.getElementById(id);

function addMetric(label, value) {
  const dt=document.createElement("dt"), dd=document.createElement("dd");
  dt.textContent=label; dd.textContent=value; $("metrics").append(dt,dd);
}

function show(proof) {
  $("empty").classList.add("hidden");
  $("content").classList.remove("hidden");
  $("goal").textContent=proof.goal;
  $("stage").textContent=proof.stage || "PLANNED";
  $("time").textContent=new Date(proof.created_at).toLocaleString();
  $("expires").textContent=new Date(proof.expires_at).toLocaleTimeString();
  $("rawImage").src=proof.images.raw;
  $("safeImage").src=proof.images.sanitized;
  $("sentImage").src=proof.images.sent;
  for (const item of proof.tokens || []) {
    const chip=document.createElement("span"); chip.className="chip";
    chip.textContent=`${item.token} · ${item.layer}`; $("tokens").append(chip);
  }
  if (!(proof.tokens || []).length) $("tokens").textContent="No sensitive regions detected.";
  addMetric("Pixels disclosed", `${Math.round((proof.metrics.pixel_fraction || 0)*100)}%`);
  addMetric("Controls disclosed", `${proof.metrics.disclosed_elements}/${proof.metrics.observed_controls}`);
  addMetric("Semantic fraction", `${Math.round((proof.metrics.element_fraction || 0)*100)}%`);
  addMetric("Request bytes", Number(proof.metrics.request_bytes || 0).toLocaleString());
  addMetric("Local provider", proof.metrics.provider || "unknown");
  for (const item of proof.safe_metadata || []) {
    const row=document.createElement("div"); row.className="meta-row";
    for (const value of [item.id,item.role,item.label]) {
      const span=document.createElement("span"); span.textContent=value; row.append(span);
    }
    row.children[1].className="meta-role"; $("metadata").append(row);
  }
  if (!(proof.safe_metadata || []).length) $("metadata").textContent="No controls disclosed.";
}

chrome.storage.session.get(KEY).then((result) => {
  const proof=result[KEY];
  if (!proof || Date.now()>proof.expires_at) {
    if (proof) chrome.storage.session.remove(KEY);
    $("empty").classList.remove("hidden");
  } else show(proof);
});

$("clear").addEventListener("click", async () => {
  await chrome.storage.session.remove(KEY);
  await chrome.alarms.clear("aegis-proof-expire");
  location.reload();
});
