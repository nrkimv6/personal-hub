const TARGET_HOST_PATTERN = "https://new.land.naver.com/*";
const STORAGE_KEY = "chromeApiCaptureRecent";
const MAX_CAPTURE_ENTRIES = 300;
const REPLAY_ALLOWED_METHODS = new Set(["GET", "HEAD"]);
const SENSITIVE_HEADER_NAMES = new Set([
  "authorization",
  "cookie",
  "proxy-authorization",
  "set-cookie",
  "x-csrf-token",
  "x-xsrf-token"
]);

let captureEnabled = true;
const sessionsByTab = new Map();
const requestsById = new Map();

function nowIso() {
  return new Date().toISOString();
}

function getTabSession(tabId) {
  const key = String(tabId ?? "unknown");
  if (!sessionsByTab.has(key)) {
    sessionsByTab.set(key, {
      tabId,
      captures: [],
      captureWarnings: [
        "webRequest may miss response bodies and in-memory cache hits."
      ],
      updatedAt: nowIso()
    });
  }
  return sessionsByTab.get(key);
}

function cloneHeader(header) {
  return {
    name: header.name,
    value: header.value ?? header.binaryValue ?? ""
  };
}

function maskHeaders(headers = [], includeSensitive = false) {
  return headers.map((header) => {
    const copy = cloneHeader(header);
    if (!includeSensitive && SENSITIVE_HEADER_NAMES.has(copy.name.toLowerCase())) {
      copy.value = "[masked-sensitive-header]";
      copy.masked = true;
    }
    return copy;
  });
}

function summarizeRequestBody(requestBody) {
  if (!requestBody) {
    return null;
  }
  if (requestBody.error) {
    return { kind: "unavailable", error: requestBody.error };
  }
  if (requestBody.formData) {
    const fields = Object.entries(requestBody.formData).map(([name, values]) => ({
      name,
      valueCount: Array.isArray(values) ? values.length : 0
    }));
    return { kind: "formData", fields };
  }
  if (requestBody.raw) {
    const totalBytes = requestBody.raw.reduce((sum, part) => {
      if (part.bytes) {
        return sum + part.bytes.byteLength;
      }
      if (part.file) {
        return sum;
      }
      return sum;
    }, 0);
    return {
      kind: "raw",
      partCount: requestBody.raw.length,
      byteLength: totalBytes,
      note: "binary request body is summarized only"
    };
  }
  return { kind: "unknown" };
}

function normalizeRequest(details) {
  return {
    id: details.requestId,
    requestId: details.requestId,
    tabId: details.tabId,
    frameId: details.frameId,
    source: "webRequest",
    method: details.method,
    url: details.url,
    type: details.type,
    startedAt: details.timeStamp,
    updatedAt: details.timeStamp,
    requestBody: summarizeRequestBody(details.requestBody),
    requestHeaders: [],
    responseHeaders: [],
    redirects: [],
    statusCode: null,
    terminalStatus: "pending",
    error: null,
    captureWarnings: [
      "webRequest does not expose response body and may not fire for in-memory cache hits."
    ]
  };
}

async function persistSession(tabId) {
  const session = getTabSession(tabId);
  session.captures = session.captures.slice(-MAX_CAPTURE_ENTRIES);
  session.updatedAt = nowIso();
  if (chrome.storage?.session) {
    await chrome.storage.session.set({ [STORAGE_KEY]: session.captures });
  }
}

function upsertCapture(tabId, entry) {
  const session = getTabSession(tabId);
  const existingIndex = session.captures.findIndex((capture) => capture.id === entry.id);
  if (existingIndex >= 0) {
    session.captures[existingIndex] = { ...session.captures[existingIndex], ...entry };
  } else {
    session.captures.push(entry);
  }
  void persistSession(tabId);
}

function onBeforeRequest(details) {
  if (!captureEnabled) {
    return;
  }
  const entry = normalizeRequest(details);
  requestsById.set(details.requestId, entry);
  upsertCapture(details.tabId, entry);
}

function onBeforeSendHeaders(details) {
  if (!captureEnabled) {
    return;
  }
  const entry = requestsById.get(details.requestId) ?? normalizeRequest(details);
  entry.requestHeaders = maskHeaders(details.requestHeaders ?? []);
  entry.updatedAt = details.timeStamp;
  requestsById.set(details.requestId, entry);
  upsertCapture(details.tabId, entry);
}

function onHeadersReceived(details) {
  if (!captureEnabled) {
    return;
  }
  const entry = requestsById.get(details.requestId) ?? normalizeRequest(details);
  entry.statusCode = details.statusCode;
  entry.statusLine = details.statusLine;
  entry.responseHeaders = maskHeaders(details.responseHeaders ?? []);
  entry.updatedAt = details.timeStamp;
  requestsById.set(details.requestId, entry);
  upsertCapture(details.tabId, entry);
}

function onBeforeRedirect(details) {
  if (!captureEnabled) {
    return;
  }
  const entry = requestsById.get(details.requestId) ?? normalizeRequest(details);
  entry.redirects.push({
    fromUrl: details.url,
    toUrl: details.redirectUrl,
    statusCode: details.statusCode,
    at: details.timeStamp
  });
  entry.statusCode = details.statusCode;
  entry.updatedAt = details.timeStamp;
  requestsById.set(details.requestId, entry);
  upsertCapture(details.tabId, entry);
}

function onCompleted(details) {
  if (!captureEnabled) {
    return;
  }
  const entry = requestsById.get(details.requestId) ?? normalizeRequest(details);
  entry.statusCode = details.statusCode;
  entry.fromCache = Boolean(details.fromCache);
  entry.ip = details.ip ?? null;
  entry.terminalStatus = "completed";
  entry.completedAt = details.timeStamp;
  entry.updatedAt = details.timeStamp;
  requestsById.delete(details.requestId);
  upsertCapture(details.tabId, entry);
}

function onErrorOccurred(details) {
  if (!captureEnabled) {
    return;
  }
  const entry = requestsById.get(details.requestId) ?? normalizeRequest(details);
  entry.terminalStatus = "error";
  entry.error = details.error;
  entry.completedAt = details.timeStamp;
  entry.updatedAt = details.timeStamp;
  requestsById.delete(details.requestId);
  upsertCapture(details.tabId, entry);
}

function mergePageHookCapture(payload, sender) {
  if (!captureEnabled) {
    return { ok: true, ignored: "capture-disabled" };
  }
  const tabId = sender.tab?.id ?? payload.tabId ?? -1;
  const id = `pageHook:${payload.hookId}`;
  const entry = {
    id,
    hookId: payload.hookId,
    tabId,
    source: "pageHook",
    hookType: payload.hookType,
    method: payload.method,
    url: payload.url,
    statusCode: payload.statusCode ?? null,
    terminalStatus: payload.error ? "error" : "completed",
    requestHeaders: maskHeaders(payload.requestHeaders ?? []),
    requestBody: payload.requestBody ?? null,
    responseHeaders: maskHeaders(payload.responseHeaders ?? []),
    responseBody: payload.responseBody ?? null,
    error: payload.error ?? null,
    startedAt: payload.startedAt,
    completedAt: payload.completedAt,
    updatedAt: Date.now(),
    captureWarnings: payload.captureWarnings ?? []
  };
  upsertCapture(tabId, entry);
  return { ok: true };
}

function buildExportBody(captures, format, includeSensitive) {
  const serializable = captures.map((capture) => ({
    ...capture,
    requestHeaders: maskHeaders(capture.requestHeaders ?? [], includeSensitive),
    responseHeaders: maskHeaders(capture.responseHeaders ?? [], includeSensitive)
  }));
  if (format === "ndjson") {
    return serializable.map((capture) => JSON.stringify(capture)).join("\n") + "\n";
  }
  return JSON.stringify({
    exportedAt: nowIso(),
    targetHostPattern: TARGET_HOST_PATTERN,
    includeSensitive,
    warning: "Exports can contain sensitive URL, header, and body data. Do not commit capture logs.",
    captures: serializable
  }, null, 2);
}

function exportCaptures(format = "json", includeSensitive = false, tabId = null) {
  const captures = tabId == null
    ? Array.from(sessionsByTab.values()).flatMap((session) => session.captures)
    : getTabSession(tabId).captures;
  const normalizedFormat = format === "ndjson" ? "ndjson" : "json";
  return {
    mime: normalizedFormat === "ndjson" ? "application/x-ndjson" : "application/json",
    filename: `chrome-api-capture-${new Date().toISOString().replace(/[:.]/g, "-")}.${normalizedFormat}`,
    body: buildExportBody(captures, normalizedFormat, includeSensitive)
  };
}

async function replayCapture(entryId, tabId) {
  const session = getTabSession(tabId);
  const entry = session.captures.find((capture) => capture.id === entryId);
  if (!entry) {
    return { ok: false, blocked: true, reason: "capture entry not found" };
  }
  const method = String(entry.method ?? "GET").toUpperCase();
  if (!REPLAY_ALLOWED_METHODS.has(method)) {
    return {
      ok: false,
      blocked: true,
      reason: `replay blocked: ${method} is a mutating method; only GET/HEAD are allowed by default`
    };
  }
  const safeHeaders = {};
  for (const header of entry.requestHeaders ?? []) {
    const name = header.name.toLowerCase();
    if (!SENSITIVE_HEADER_NAMES.has(name) && header.value && !header.masked) {
      safeHeaders[header.name] = header.value;
    }
  }
  const response = await fetch(entry.url, {
    method,
    headers: safeHeaders,
    credentials: "omit",
    cache: "no-store",
    redirect: "manual"
  });
  return {
    ok: true,
    status: response.status,
    statusText: response.statusText,
    blocked: false
  };
}

async function handleMessage(message, sender) {
  const action = message?.action;
  const tabId = message?.tabId ?? sender.tab?.id ?? null;
  if (action === "getState") {
    const session = tabId == null
      ? { captures: Array.from(sessionsByTab.values()).flatMap((item) => item.captures) }
      : getTabSession(tabId);
    return {
      captureEnabled,
      targetHostPattern: TARGET_HOST_PATTERN,
      captures: session.captures.slice(-MAX_CAPTURE_ENTRIES),
      captureWarnings: session.captureWarnings ?? []
    };
  }
  if (action === "setCaptureEnabled") {
    captureEnabled = Boolean(message.enabled);
    return { ok: true, captureEnabled };
  }
  if (action === "clear") {
    if (message.scope === "all") {
      sessionsByTab.clear();
      requestsById.clear();
      if (chrome.storage?.session) {
        await chrome.storage.session.remove(STORAGE_KEY);
      }
      return { ok: true };
    }
    getTabSession(tabId).captures = [];
    await persistSession(tabId);
    return { ok: true };
  }
  if (action === "export") {
    return exportCaptures(message.format, Boolean(message.includeSensitive), tabId);
  }
  if (action === "replay") {
    return replayCapture(message.entryId, tabId);
  }
  if (action === "pageHookCapture") {
    return mergePageHookCapture(message.payload, sender);
  }
  return { ok: false, error: `unknown action: ${action}` };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then(sendResponse)
    .catch((error) => sendResponse({ ok: false, error: String(error?.message ?? error) }));
  return true;
});

chrome.webRequest.onBeforeRequest.addListener(
  onBeforeRequest,
  { urls: [TARGET_HOST_PATTERN] },
  ["requestBody"]
);
chrome.webRequest.onBeforeSendHeaders.addListener(
  onBeforeSendHeaders,
  { urls: [TARGET_HOST_PATTERN] },
  ["requestHeaders", "extraHeaders"]
);
chrome.webRequest.onHeadersReceived.addListener(
  onHeadersReceived,
  { urls: [TARGET_HOST_PATTERN] },
  ["responseHeaders", "extraHeaders"]
);
chrome.webRequest.onBeforeRedirect.addListener(onBeforeRedirect, { urls: [TARGET_HOST_PATTERN] });
chrome.webRequest.onCompleted.addListener(onCompleted, { urls: [TARGET_HOST_PATTERN] });
chrome.webRequest.onErrorOccurred.addListener(onErrorOccurred, { urls: [TARGET_HOST_PATTERN] });
