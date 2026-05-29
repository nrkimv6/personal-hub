const PAGE_HOOK_CHANNEL = "CHROME_API_CAPTURE_PAGE_HOOK";
const EXTENSION_BRIDGE_SOURCE = "chrome-api-capture-extension";

function injectMainWorldHook() {
  const script = document.createElement("script");
  script.src = chrome.runtime.getURL("injected.js");
  script.dataset.source = EXTENSION_BRIDGE_SOURCE;
  script.onload = () => script.remove();
  (document.documentElement || document.head).appendChild(script);
}

window.addEventListener("message", (event) => {
  if (event.source !== window) {
    return;
  }
  const payload = event.data;
  if (!payload || payload.channel !== PAGE_HOOK_CHANNEL || payload.source !== EXTENSION_BRIDGE_SOURCE) {
    return;
  }
  chrome.runtime.sendMessage({
    action: "pageHookCapture",
    payload: payload.capture
  });
});

injectMainWorldHook();
