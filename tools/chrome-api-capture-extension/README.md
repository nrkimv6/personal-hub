# Chrome API Capture Test Extension

Load-unpacked Chrome MV3 test extension for observing API traffic on `https://new.land.naver.com/*` without using `chrome.debugger`, CDP, or DevTools attachment.

## Scope

- Allowed target scope: `https://new.land.naver.com/*`.
- Intended verification URL: `https://new.land.naver.com/houses?ms=2AIjRa,3zhLQi,16&a=DDDGG:JWJT:SGJT:VL&b=B1:B2&d=50&e=RETAIL&f=15000&g=25000&h=28&i=81&j=20&v=NOLOAN`.
- The extension observes requests from a manually opened tab. It must not be used for automated external service calls, bulk replay, access-control bypass, or scraping.
- `webRequest` captures request/response metadata. Response body capture is best-effort through page-context `fetch` and `XMLHttpRequest` hooks.

## Sensitive Data Warning

Captured URLs, headers, request bodies, and response bodies can contain cookies, tokens, user identifiers, CSRF values, or private query parameters. Cookie, Authorization, and CSRF-like headers are masked by default in memory display and export. Do not commit exported JSON, NDJSON, screenshots, or captured samples.

## Install

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose Load unpacked.
4. Select `tools/chrome-api-capture-extension`.
5. Open the target `https://new.land.naver.com/*` tab manually.
6. Use the popup to toggle capture, inspect recent requests, clear local memory, or export JSON/NDJSON.

## Replay Guard

Replay is a manual popup action. GET and HEAD entries are the only methods allowed by default. POST, PUT, PATCH, DELETE, and other mutating methods return a blocked reason and are not sent. Sensitive headers are not replayed.

## Local Fixture

`fixtures/local-api.html` contains manual buttons for fetch GET, fetch POST, and XHR GET. It uses relative URLs so it can be served from a local static server without calling an external service. Because the extension host permission is intentionally limited to `https://new.land.naver.com/*`, do not broaden committed permissions for the fixture. If a one-off local browser check is needed, use a temporary local copy outside the repository and discard it before commit.

## Manual Smoke Handoff

The manual Chrome smoke belongs to the merge-test owner. Open the target URL once, confirm that metadata appears in the popup, confirm that pageHook body capture either succeeds or reports a limitation, export JSON/NDJSON if needed, and verify that no captured export file remains in the repository.
