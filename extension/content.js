// CortexAgent content script — extracts page text/DOM for context
let lastExtract = "";
let extractTimer = null;

function extractPageText() {
  // Get the main content, excluding scripts, styles, and hidden elements
  const body = document.body;
  if (!body) return "";

  // Clone to avoid modifying the live DOM
  const clone = body.cloneNode(true);

  // Remove non-content elements
  const removals = clone.querySelectorAll(
    "script, style, noscript, svg, canvas, video, audio, iframe, " +
    "[hidden], [aria-hidden='true'], .hidden, .visually-hidden"
  );
  removals.forEach((el) => el.remove());

  // Get text content
  let text = clone.textContent || "";

  // Clean up whitespace
  text = text.replace(/\s+/g, " ").trim();

  // Limit to 32KB
  if (text.length > 32000) {
    text = text.substring(0, 16000) + "\n\n... [truncated] ...\n\n" + text.substring(text.length - 8000);
  }

  return text;
}

// Listen for requests from the sidebar
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getPageContext") {
    const text = extractPageText();
    sendResponse({ text, url: window.location.href, title: document.title });
  }
  return true; // Keep the message channel open for async response
});

// Auto-extract on page load and store for later use
lastExtract = extractPageText();
