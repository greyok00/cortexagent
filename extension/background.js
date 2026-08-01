// CortexAgent background service worker
// Manages WebSocket connection to the tray app and handles extension lifecycle

let ws = null;
let reconnectTimer = null;
let connectionState = "disconnected";

// ── Connection management ────────────────────────────────────────────────
function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["host", "token"], (items) => {
      resolve({
        host: items.host || "127.0.0.1:8090",
        token: items.token || "",
      });
    });
  });
}

async function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  const settings = await getSettings();
  const url = `ws://${settings.host}/mcp`;

  try {
    ws = new WebSocket(url);

    ws.onopen = () => {
      connectionState = "connected";
      updateIcon("connected");
    };

    ws.onclose = () => {
      connectionState = "disconnected";
      updateIcon("disconnected");
      scheduleReconnect();
    };

    ws.onerror = () => {
      connectionState = "error";
      updateIcon("disconnected");
      scheduleReconnect();
    };

    ws.onmessage = (event) => {
      // Forward messages to the sidebar if it's open
      chrome.runtime.sendMessage({
        type: "mcp_response",
        data: event.data,
      }).catch(() => {
        // Sidebar not open — ignore
      });
    };
  } catch (e) {
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, 5000);
}

// ── Icon state ────────────────────────────────────────────────────────────
function updateIcon(state) {
  const color = state === "connected" ? [63, 185, 80, 255] : [248, 81, 73, 255];
  // Create a simple colored badge
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({
    text: state === "connected" ? "ON" : "OFF",
  });
}

// ── Extension lifecycle ──────────────────────────────────────────────────
chrome.runtime.onStartup.addListener(() => {
  connect();
  // Ensure sidebar opens on icon click
  if (chrome.sidePanel) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  }
});

chrome.runtime.onInstalled.addListener(() => {
  connect();
  if (chrome.sidePanel) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  }
});

// Click handler — opens sidebar if closed
chrome.action.onClicked.addListener((tab) => {
  if (chrome.sidePanel) {
    chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
  }
});

// Handle messages from the sidebar
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "get_connection_status") {
    sendResponse({ status: connectionState });
    return true;
  }
  if (request.type === "reconnect") {
    if (ws) ws.close();
    connect();
    sendResponse({ status: "reconnecting" });
    return true;
  }
});

// Keep the service worker alive
chrome.alarms.create("heartbeat", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "heartbeat") {
    // Check connection health
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      connect();
    }
  }
});
