// MV3 service worker. Stateless per instructions.md's Key Extension
// Constraints — no module-level state persists reliably between events, so
// every setting is re-read from chrome.storage.local on each message.
const DEFAULT_BACKEND_URL = "http://localhost:8000";

async function getBackendUrl() {
  const { backendUrl } = await chrome.storage.local.get("backendUrl");
  return backendUrl || DEFAULT_BACKEND_URL;
}

async function runSearch(query, mode, level) {
  const backendUrl = await getBackendUrl();
  const res = await fetch(`${backendUrl}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, level }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Backend returned ${res.status}: ${detail}`);
  }
  return res.json();
}

async function openTabsSequentially(urls) {
  for (let i = 0; i < urls.length; i++) {
    await chrome.tabs.create({ url: urls[i], active: i === 0 });
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "SEARCH") {
    runSearch(message.query, message.mode, message.level)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true; // keep the message channel open for the async sendResponse
  }

  if (message?.type === "OPEN_TABS") {
    openTabsSequentially(message.urls || [])
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true;
  }

  return false;
});
