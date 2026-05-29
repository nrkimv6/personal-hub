let activeTabId = null;
let currentCaptures = [];
let sourceFilter = "all";

function send(action, payload = {}) {
  return chrome.runtime.sendMessage({ action, tabId: activeTabId, ...payload });
}

function methodAllowsReplay(method) {
  return ["GET", "HEAD"].includes(String(method || "").toUpperCase());
}

function requestSummary(capture) {
  return {
    id: capture.id,
    source: capture.source,
    method: capture.method,
    url: capture.url,
    statusCode: capture.statusCode,
    terminalStatus: capture.terminalStatus,
    maskedHeaders: [...(capture.requestHeaders ?? []), ...(capture.responseHeaders ?? [])]
      .some((header) => header.masked || header.value === "[masked-sensitive-header]"),
    responseBodyCaptured: Boolean(capture.responseBody?.text),
    responseBodyTruncated: Boolean(capture.responseBody?.truncated),
    warnings: capture.captureWarnings ?? []
  };
}

function renderDetail(capture) {
  document.getElementById("captureDetail").textContent = JSON.stringify(requestSummary(capture), null, 2);
}

async function replayEntry(capture) {
  const guard = document.getElementById("replayGuard");
  if (!methodAllowsReplay(capture.method)) {
    guard.textContent = `Replay blocked: ${capture.method} is a mutating method.`;
    renderDetail(capture);
    return;
  }
  const result = await send("replay", { entryId: capture.id });
  guard.textContent = result.blocked
    ? result.reason
    : `Replay completed: HTTP ${result.status} ${result.statusText || ""}`;
}

function renderCaptures() {
  const list = document.getElementById("captureList");
  list.replaceChildren();
  const filtered = currentCaptures.filter((capture) => (
    sourceFilter === "all" || capture.source === sourceFilter
  ));
  for (const capture of filtered.slice().reverse()) {
    const row = document.createElement("li");
    row.className = "capture-row";

    const method = document.createElement("span");
    method.className = "method";
    method.textContent = capture.method || "-";

    const status = document.createElement("span");
    status.className = "status";
    status.textContent = capture.statusCode || capture.terminalStatus || "-";

    const source = document.createElement("span");
    source.className = "source";
    source.textContent = capture.source || "-";

    const url = document.createElement("span");
    url.className = "url";
    url.title = capture.url || "";
    url.textContent = capture.url || "";

    const replay = document.createElement("button");
    replay.type = "button";
    replay.textContent = methodAllowsReplay(capture.method) ? "Replay" : "Blocked";
    replay.disabled = !methodAllowsReplay(capture.method);
    replay.title = methodAllowsReplay(capture.method)
      ? "Replay GET/HEAD request"
      : "Replay blocked for mutating methods";
    replay.addEventListener("click", () => replayEntry(capture));

    row.append(method, status, source, url, replay);
    row.addEventListener("click", () => renderDetail(capture));
    list.appendChild(row);
  }
}

async function downloadExport(format) {
  const payload = await send("export", { format, includeSensitive: false });
  const blob = new Blob([payload.body], { type: payload.mime });
  const url = URL.createObjectURL(blob);
  await chrome.downloads.download({
    url,
    filename: payload.filename,
    saveAs: true
  });
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

async function loadState() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTabId = tab?.id ?? null;
  const state = await send("getState");
  currentCaptures = state.captures ?? [];
  document.getElementById("captureToggle").checked = Boolean(state.captureEnabled);
  document.getElementById("targetHost").textContent = state.targetHostPattern || "https://new.land.naver.com/*";
  renderCaptures();
}

document.getElementById("captureToggle").addEventListener("change", async (event) => {
  await send("setCaptureEnabled", { enabled: event.target.checked });
  await loadState();
});

document.getElementById("sourceFilter").addEventListener("change", (event) => {
  sourceFilter = event.target.value;
  renderCaptures();
});

document.getElementById("clearTab").addEventListener("click", async () => {
  await send("clear", { scope: "tab" });
  await loadState();
});

document.getElementById("clearAll").addEventListener("click", async () => {
  await send("clear", { scope: "all" });
  await loadState();
});

document.getElementById("exportJson").addEventListener("click", () => downloadExport("json"));
document.getElementById("exportNdjson").addEventListener("click", () => downloadExport("ndjson"));

loadState();
