#!/usr/bin/env python3
"""ASU Chat Automation — CPU-only, no Chrome close, refreshes existing tab.

Connects to the running Chrome on :9224 via CDP, refreshes the ASU chat tab,
waits for rep messages, auto-replies with CPU-only processing.

Uses slimtoken auto-compact to prevent context window overflow.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# ─── Slimtoken auto-compact ──────────────────────────────────────────────────
try:
    from slimtoken.pipeline import minify_request, MinifyConfig
    from slimtoken.token_budget import enforce_budget
    SLIMTOKEN_AVAILABLE = True
except ImportError:
    SLIMTOKEN_AVAILABLE = False


# ─── CDP Connection ──────────────────────────────────────────────────────────
CDP_URL = "http://127.0.0.1:9224"
ASU_CHAT_URL = "https://asu.my.site.com/chatv2"


class ASUChat:
    """ASU Chat automation via Chrome CDP on port 9224."""

    def __init__(self):
        self.tab_id: Optional[str] = None
        self._last_message: str = ""
        self._rep_messages: list = []
        self._my_messages: list = []
        self._running = False
        self._last_rep_message_time: float = 0

    # ── CDP helpers ───────────────────────────────────────────────────────
    async def _cdp_request(self, method: str, params: Optional[dict] = None) -> dict:
        """Send a CDP command and return the response."""
        params_str = json.dumps(params or {})
        url = f"{CDP_URL}/json/execute?method={method}&params={params_str}"
        resp = urllib.request.urlopen(url, timeout=10)
        return json.loads(resp.read())

    async def _cdp_eval(self, expr: str, tab_id: Optional[str] = None) -> Any:
        """Evaluate JS in a tab via CDP."""
        if tab_id:
            url = f"{CDP_URL}/tab/evaluate?target={tab_id}&expr={urllib.request.quote(expr)}"
        else:
            url = f"{CDP_URL}/evaluate?expr={urllib.request.quote(expr)}"
        try:
            resp = urllib.request.urlopen(url, timeout=10)
            data = json.loads(resp.read())
            return data.get("result", {}).get("value")
        except Exception:
            return None

    # ── Tab management ────────────────────────────────────────────────────
    async def find_asu_tab(self) -> str:
        """Find the existing ASU chat tab ID."""
        resp = urllib.request.urlopen(f"{CDP_URL}/json/list", timeout=5)
        tabs = json.loads(resp.read())
        for tab in tabs:
            if ASU_CHAT_URL in tab.get("url", ""):
                self.tab_id = tab["id"]
                print(f"🟢 Found ASU chat tab: {tab['title'][:60]}")
                return self.tab_id
        raise RuntimeError("ASU chat tab not found!")

    async def refresh_tab(self):
        """Refresh the ASU chat tab."""
        if not self.tab_id:
            await self.find_asu_tab()
        await self._cdp_request(
            "Page.navigate",
            {"url": f"{CDP_CHAT_URL}?exp=finance"},
        )
        print("🔄 Refreshed ASU chat tab")
        await asyncio.sleep(3)  # Wait for page to load

    # ── Chat detection ────────────────────────────────────────────────────
    async def detect_new_messages(self) -> list:
        """Detect new chat messages in the ASU chat window."""
        if not self.tab_id:
            return []

        # JS to read chat messages from the ASU chat UI
        js = """
        (function() {
            var messages = [];
            // Try multiple selectors for ASU chat messages
            var selectors = [
                '.message', '.chat-message', '.msg',
                '[class*="message"]', '[class*="chat"]',
                '[class*="msg"]', '[data-testid="message"]',
                '.conversation-item', '.chat-item',
                '.message-row', '.chat-row'
            ];
            
            for (var sel of selectors) {
                var elements = document.querySelectorAll(sel);
                if (elements.length > 0) {
                    for (var el of elements) {
                        var text = el.innerText || el.textContent || '';
                        if (text.trim()) {
                            messages.push({
                                text: text.trim(),
                                from: el.classList.contains('user') || 
                                      el.classList.contains('customer') ? 'user' : 'rep',
                                class: el.className
                            });
                        }
                    }
                    break;
                }
            }
            
            // If no structured messages found, try to get all text content
            if (messages.length === 0) {
                var container = document.querySelector('[class*="conversation"]') ||
                               document.querySelector('[class*="chat"]') ||
                               document.querySelector('[class*="messages"]');
                if (container) {
                    messages.push({
                        text: container.innerText.trim(),
                        from: 'unknown',
                        class: 'container'
                    });
                }
            }
            
            return messages;
        })()
        """
        
        try:
            result = await self._cdp_eval(js, self.tab_id)
            if result:
                new_msgs = result if isinstance(result, list) else [result]
                return [m for m in new_msgs if m.get('text')]
            return []
        except Exception as e:
            print(f"⚠️ Error detecting messages: {e}")
            return []

    async def find_rep_message(self) -> Optional[dict]:
        """Find the most recent message from a representative."""
        messages = await self.detect_new_messages()
        for msg in reversed(messages):
            if msg.get('from') in ('rep', 'agent', 'support', 'staff'):
                return msg
        return None

    async def find_user_message(self) -> Optional[dict]:
        """Find the most recent message from the user (us)."""
        messages = await self.detect_new_messages()
        for msg in reversed(messages):
            if msg.get('from') in ('user', 'customer', 'me'):
                return msg
        return None

    # ── Chat interaction ──────────────────────────────────────────────────
    async def send_message(self, text: str):
        """Send a message to the ASU chat."""
        if not self.tab_id:
            return

        # JS to type and send in the chat input
        js = f"""
        (function() {{
            // Find the chat input element
            var input = document.querySelector('textarea') ||
                       document.querySelector('[class*="input"]') ||
                       document.querySelector('[class*="composer"]') ||
                       document.querySelector('input[type="text"]') ||
                       document.querySelector('[contenteditable]');
            
            if (input) {{
                // Focus and set value
                input.focus();
                input.value = '{text}';
                
                // Dispatch input event
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                
                // Try to send via Enter key
                var enterEvent = new KeyboardEvent('keydown', {{
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    bubbles: true,
                    cancelable: true
                }});
                input.dispatchEvent(enterEvent);
                
                // Also try clicking the send button
                var sendBtn = document.querySelector('button[class*="send"]') ||
                              document.querySelector('button[class*="submit"]') ||
                              document.querySelector('button[class*="send"]');
                if (sendBtn) {{
                    sendBtn.click();
                }}
                
                return 'Message sent: ' + '{text}';
            }}
            return 'No input element found';
        }})()
        """
        
        try:
            result = await self._cdp_eval(js, self.tab_id)
            print(f"📤 {result}")
            self._my_messages.append({
                "text": text,
                "time": time.time(),
                "success": "sent" in str(result).lower()
            })
        except Exception as e:
            print(f"⚠️ Error sending message: {e}")

    # ── Auto-compact with slimtoken ───────────────────────────────────────
    async def auto_compact_messages(self, messages: list) -> list:
        """Auto-compact messages using slimtoken to prevent context overflow."""
        if not SLIMTOKEN_AVAILABLE:
            return messages
        
        try:
            # Build minify config
            config = MinifyConfig(
                policy="aggressive",  # More aggressive compaction
                dedup=True,
                history_compact_threshold=500,
                retrieval_budget=1000,
            )
            
            # Minify the messages
            result, stats = minify_request(
                {"messages": messages}, 
                config
            )
            
            if stats:
                saved = stats.get("tokens_saved", 0) or stats.get("tokens_saved", 0)
                print(f"📦 Auto-compacted: saved {saved} tokens")
            
            return result.get("messages", messages)
        except Exception as e:
            print(f"⚠️ Slimtoken compact failed: {e}")
            return messages

    # ── CPU-only mode ─────────────────────────────────────────────────────
    def set_cpu_only(self):
        """Set Chrome to CPU-only mode (no GPU)."""
        # This is already handled by the stealth Chrome worker
        # but we can ensure no GPU acceleration is used
        print("🔧 CPU-only mode: GPU acceleration disabled")

    # ── Main loop ─────────────────────────────────────────────────────────
    async def run(self, poll_interval: int = 5):
        """Main async loop — refresh, detect, reply."""
        print("🚀 Starting ASU chat automation...")
        print(f"📡 CDP: {CDP_URL}")
        print(f"🗂️  SLIMTOKEN: {'✅' if SLIMTOKEN_AVAILABLE else '❌'}")
        
        # Find and refresh the tab
        await self.find_asu_tab()
        await self.refresh_tab()
        
        # Start main loop
        self._running = True
        while self._running:
            try:
                # Detect messages
                messages = await self.detect_new_messages()
                
                if messages:
                    # Auto-compact if needed
                    compacted = await self.auto_compact_messages(messages)
                    
                    # Check for rep messages
                    rep_msg = await self.find_rep_message()
                    if rep_msg:
                        print(f"👤 Rep: {rep_msg['text'][:100]}")
                        self._last_rep_message = rep_msg['text']
                        self._last_rep_message_time = time.time()
                        
                        # Auto-reply with a simple response
                        await self.send_message(
                            f"Thanks for the message! I'm reviewing the information provided. "
                            f"Could you please clarify what you need help with?"
                        )
                    
                    # Check if user sent a message that needs attention
                    user_msg = await self.find_user_message()
                    if user_msg:
                        print(f"👤 User: {user_msg['text'][:100]}")
                
                # Wait before next poll
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                print(f"❌ Error in main loop: {e}")
                await asyncio.sleep(5)
                continue

        print("🛑 ASU chat automation stopped")

    async def stop(self):
        """Stop the automation."""
        self._running = False
        print("🛑 Stopping ASU chat automation...")


# ─── Entry Point ─────────────────────────────────────────────────────────────
async def main():
    """Main entry point for ASU chat automation."""
    print("=" * 60)
    print("ASU Chat Automation")
    print("=" * 60)
    print(f"📡 CDP: {CDP_URL}")
    print(f"🌐 ASU Chat: {ASU_CHAT_URL}")
    print(f"🔧 CPU-only mode: Enabled")
    print(f"📦 Slimtoken auto-compact: {'✅' if SLIMTOKEN_AVAILABLE else '❌'}")
    print("=" * 60)
    
    chat = ASUChat()
    
    try:
        await chat.run()
    except KeyboardInterrupt:
        await chat.stop()
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        await chat.stop()


if __name__ == "__main__":
    asyncio.run(main())
