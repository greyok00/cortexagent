// CortexAgent Sidebar — chat UI, STT, TTS, connection status
const messages = document.getElementById("messages");
const input = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const micBtn = document.getElementById("micBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const settingsBtn = document.getElementById("settingsBtn");
const settingsPanel = document.getElementById("settingsPanel");
const hostInput = document.getElementById("hostInput");
const tokenInput = document.getElementById("tokenInput");
const saveSettings = document.getElementById("saveSettings");
const toast = document.getElementById("toast");

let isListening = false;
let recognition = null;
let ttsEnabled = false;
let msgId = 1;

// ── Settings ──────────────────────────────────────────────────────────────
function loadSettings() {
  return new Promise((resolve) => {
    if (typeof chrome !== 'undefined' && chrome.storage) {
      chrome.storage.sync.get(["host", "token"], (items) => {
        hostInput.value = items.host || "127.0.0.1:8090";
        tokenInput.value = items.token || "";
        resolve(items);
      });
    } else {
      // Fallback if not in extension context
      hostInput.value = "127.0.0.1:8090";
      tokenInput.value = "";
      resolve({ host: "127.0.0.1:8090", token: "" });
    }
  });
}

function saveSettings() {
  const host = hostInput.value.trim() || "127.0.0.1:8090";
  const token = tokenInput.value.trim();
  chrome.storage.sync.set({ host, token }, () => {
    showToast("Settings saved");
    settingsPanel.classList.remove("open");
    checkConnection();
  });
}

settingsBtn.addEventListener("click", () => {
  settingsPanel.classList.toggle("open");
});

saveSettings.addEventListener("click", saveSettings);

// ── Connection check via HTTP ─────────────────────────────────────────────
function getBaseUrl() {
  const host = hostInput.value.trim() || "127.0.0.1:8090";
  return `http://${host}`;
}

function getAuthHeaders() {
  const token = tokenInput.value.trim();
  return token ? { "Authorization": `Bearer ${token}` } : {};
}

async function checkConnection() {
  const url = `${getBaseUrl()}/health`;
  console.log("[CortexAgent] Checking connection to", url);
  try {
    const resp = await fetch(url, {
      headers: getAuthHeaders(),
      signal: AbortSignal.timeout(3000),
    });
    if (resp.ok) {
      console.log("[CortexAgent] Connected");
      statusDot.className = "status-dot connected";
      statusText.textContent = "connected";
      sendBtn.disabled = false;
      return true;
    }
    console.log("[CortexAgent] Health check returned", resp.status);
  } catch (e) {
    console.log("[CortexAgent] Connection failed:", e.message);
  }
  statusDot.className = "status-dot disconnected";
  statusText.textContent = "disconnected";
  sendBtn.disabled = true;
  return false;
}

// ── Chat ──────────────────────────────────────────────────────────────────
function append(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function showToast(text) {
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3000);
}

async function sendMessage(text) {
  append("user", text);
  input.value = "";
  sendBtn.disabled = true;

  // Get page context from content script
  let pageContext = "";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      const response = await chrome.tabs.sendMessage(tab.id, { action: "getPageContext" });
      if (response?.text) {
        pageContext = response.text.substring(0, 8000);
      }
    }
  } catch (e) {
    // No page context
  }

  const id = msgId++;
  const payload = {
    jsonrpc: "2.0",
    method: "tools/call",
    params: {
      name: "chat",
      arguments: { message: text, context: pageContext || "" },
    },
    id: id,
  };

  try {
    const resp = await fetch(`${getBaseUrl()}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(120000),
    });
    const data = await resp.json();
    if (data.result) {
      const content = data.result?.content?.[0]?.text || JSON.stringify(data.result, null, 2);
      append("assistant", content);
      if (ttsEnabled) speak(content);
    } else if (data.error) {
      append("error", data.error.message || "Request failed");
    }
  } catch (e) {
    if (e.name === "TimeoutError" || e.name === "AbortError") {
      append("error", "Request timed out after 2 minutes. Is llama-server running?");
    } else {
      append("error", "Cannot reach CortexAgent tray. Is it running? Start with: cortexagent-tray");
    }
  }
  sendBtn.disabled = false;
}

// ── Speech-to-Text ───────────────────────────────────────────────────────
function initSpeechRecognition() {
  if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
    micBtn.style.display = "none";
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    let final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        final += event.results[i][0].transcript;
      }
    }
    if (final) {
      input.value += final;
      input.dispatchEvent(new Event("input"));
    }
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove("listening");
    micBtn.textContent = "🎤";
  };

  recognition.onerror = () => {
    isListening = false;
    micBtn.classList.remove("listening");
    micBtn.textContent = "🎤";
  };
}

micBtn.addEventListener("click", () => {
  if (!recognition) return;
  if (isListening) { recognition.stop(); return; }
  isListening = true;
  micBtn.classList.add("listening");
  micBtn.textContent = "🔴";
  recognition.start();
});

// ── Text-to-Speech ────────────────────────────────────────────────────────
function speak(text) {
  if (!ttsEnabled) return;
  const clean = text.replace(/```[\s\S]*?```/g, "(code block)").substring(0, 2000);
  chrome.tts.speak(clean, { rate: 1.0, pitch: 1.0 });
}

// ── Input handling ───────────────────────────────────────────────────────
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const text = input.value.trim();
    if (text) sendMessage(text);
  }
});

sendBtn.addEventListener("click", () => {
  const text = input.value.trim();
  if (text) sendMessage(text);
});

// ── Init ──────────────────────────────────────────────────────────────────
loadSettings().then(() => {
  checkConnection();
  setInterval(checkConnection, 15000);
  initSpeechRecognition();
});

// Listen for settings changes
chrome.storage.onChanged.addListener((changes) => {
  if (changes.host || changes.token) {
    loadSettings();
    setTimeout(checkConnection, 500);
  }
});
