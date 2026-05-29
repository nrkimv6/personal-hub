(function installChromeApiCaptureHooks() {
  const SENTINEL = "__CHROME_API_CAPTURE_HOOK_INSTALLED__";
  const PAGE_HOOK_CHANNEL = "CHROME_API_CAPTURE_PAGE_HOOK";
  const EXTENSION_BRIDGE_SOURCE = "chrome-api-capture-extension";
  const BODY_TEXT_LIMIT = 65536;

  if (window[SENTINEL]) {
    return;
  }
  window[SENTINEL] = true;

  function nextHookId(type) {
    return `${type}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  }

  function limitText(value) {
    if (value == null) {
      return null;
    }
    const text = String(value);
    if (text.length <= BODY_TEXT_LIMIT) {
      return { text, truncated: false, length: text.length, limit: BODY_TEXT_LIMIT };
    }
    return {
      text: text.slice(0, BODY_TEXT_LIMIT),
      truncated: true,
      length: text.length,
      limit: BODY_TEXT_LIMIT
    };
  }

  function headersToList(headers) {
    if (!headers) {
      return [];
    }
    if (headers instanceof Headers) {
      return Array.from(headers.entries()).map(([name, value]) => ({ name, value }));
    }
    if (Array.isArray(headers)) {
      return headers.map(([name, value]) => ({ name, value: String(value) }));
    }
    return Object.entries(headers).map(([name, value]) => ({ name, value: String(value) }));
  }

  function summarizeBody(body) {
    if (body == null) {
      return null;
    }
    if (typeof body === "string") {
      return { kind: "text", body: limitText(body) };
    }
    if (body instanceof URLSearchParams) {
      return { kind: "urlSearchParams", body: limitText(body.toString()) };
    }
    if (body instanceof FormData) {
      return {
        kind: "formData",
        fields: Array.from(body.keys()).map((name) => ({ name }))
      };
    }
    if (body instanceof Blob) {
      return { kind: "blob", size: body.size, type: body.type };
    }
    if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) {
      return { kind: "binary", byteLength: body.byteLength };
    }
    return { kind: Object.prototype.toString.call(body) };
  }

  function postCapture(capture) {
    window.postMessage({
      channel: PAGE_HOOK_CHANNEL,
      source: EXTENSION_BRIDGE_SOURCE,
      capture
    }, window.location.origin);
  }

  function requestFromFetchInput(input, init = {}) {
    if (input instanceof Request) {
      return {
        url: input.url,
        method: (init.method || input.method || "GET").toUpperCase(),
        requestHeaders: headersToList(init.headers || input.headers),
        requestBody: summarizeBody(init.body)
      };
    }
    return {
      url: String(input),
      method: (init.method || "GET").toUpperCase(),
      requestHeaders: headersToList(init.headers),
      requestBody: summarizeBody(init.body)
    };
  }

  function installFetchHook() {
    const originalFetch = window.fetch;
    window.fetch = async function captureFetch(input, init = {}) {
      const startedAt = Date.now();
      const request = requestFromFetchInput(input, init);
      const hookId = nextHookId("fetch");
      try {
        const response = await originalFetch.apply(this, arguments);
        const responseHeaders = headersToList(response.headers);
        let responseBody = null;
        const captureWarnings = [];
        try {
          responseBody = limitText(await response.clone().text());
        } catch (error) {
          captureWarnings.push(`response body unavailable: ${String(error?.message ?? error)}`);
        }
        postCapture({
          hookId,
          hookType: "fetch",
          ...request,
          responseHeaders,
          responseBody,
          statusCode: response.status,
          startedAt,
          completedAt: Date.now(),
          captureWarnings
        });
        return response;
      } catch (error) {
        postCapture({
          hookId,
          hookType: "fetch",
          ...request,
          startedAt,
          completedAt: Date.now(),
          error: String(error?.message ?? error)
        });
        throw error;
      }
    };
  }

  function installXhrHook() {
    const OriginalXhr = window.XMLHttpRequest;
    const originalOpen = OriginalXhr.prototype.open;
    const originalSend = OriginalXhr.prototype.send;
    const originalSetRequestHeader = OriginalXhr.prototype.setRequestHeader;

    OriginalXhr.prototype.open = function captureXhrOpen(method, url) {
      this.__chromeApiCapture = {
        hookId: nextHookId("xhr"),
        hookType: "xhr",
        method: String(method || "GET").toUpperCase(),
        url: String(url),
        requestHeaders: [],
        startedAt: Date.now()
      };
      return originalOpen.apply(this, arguments);
    };

    OriginalXhr.prototype.setRequestHeader = function captureXhrHeader(name, value) {
      if (this.__chromeApiCapture) {
        this.__chromeApiCapture.requestHeaders.push({ name: String(name), value: String(value) });
      }
      return originalSetRequestHeader.apply(this, arguments);
    };

    OriginalXhr.prototype.send = function captureXhrSend(body) {
      const capture = this.__chromeApiCapture || {
        hookId: nextHookId("xhr"),
        hookType: "xhr",
        method: "GET",
        url: "",
        requestHeaders: [],
        startedAt: Date.now()
      };
      capture.requestBody = summarizeBody(body);
      this.addEventListener("loadend", () => {
        const responseHeaders = this.getAllResponseHeaders()
          .trim()
          .split(/\r?\n/)
          .filter(Boolean)
          .map((line) => {
            const separator = line.indexOf(":");
            return {
              name: separator >= 0 ? line.slice(0, separator).trim() : line,
              value: separator >= 0 ? line.slice(separator + 1).trim() : ""
            };
          });
        postCapture({
          ...capture,
          statusCode: this.status,
          responseHeaders,
          responseBody: limitText(this.responseType && this.responseType !== "text" ? "" : this.responseText),
          completedAt: Date.now()
        });
      });
      return originalSend.apply(this, arguments);
    };
  }

  installFetchHook();
  installXhrHook();
})();
