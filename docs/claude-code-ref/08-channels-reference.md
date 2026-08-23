# Claude Code Channels Reference

> Source: https://code.claude.com/docs/en/channels-reference.md
> Pulled 2026-08-11

> Note: Channels are in **research preview**. Team and Enterprise organizations
> must explicitly enable them.

## What channels are

A channel is an MCP server that pushes events into a Claude Code session so
Claude can react to things happening outside the terminal.

- **One-way channels**: forward alerts, webhooks, monitoring events for Claude to act on
- **Two-way channels**: chat bridges that also expose a reply tool so Claude can send messages back

## Requirements

The only hard requirement is the `@modelcontextprotocol/sdk` package and a
Node.js-compatible runtime. Bun, Node, and Deno all work.

Your server needs to:

1. Declare the `claude/channel` capability so Claude Code registers a notification listener
2. Emit `notifications/claude/channel` events when something happens
3. Connect over stdio transport (Claude Code spawns your server as a subprocess)

## Minimal example (Bun)

```ts
#!/usr/bin/env bun
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'

const mcp = new Server(
  { name: 'webhook', version: '0.0.1' },
  {
    capabilities: { experimental: { 'claude/channel': {} } },
    instructions: 'Events from the webhook channel arrive as <channel source="webhook" ...>.',
  },
)
await mcp.connect(new StdioServerTransport())

Bun.serve({
  port: 8788,
  hostname: '127.0.0.1',
  async fetch(req) {
    const body = await req.text()
    await mcp.notification({
      method: 'notifications/claude/channel',
      params: { content: body, meta: { path: new URL(req.url).pathname } },
    })
    return new Response('ok')
  },
})
```

## Test during the research preview

```bash
claude --dangerously-load-development-channels server:webhook
```

## Notification format

```ts
await mcp.notification({
  method: 'notifications/claude/channel',
  params: {
    content: 'event body',
    meta: { key1: 'val1', key2: 'val2' },  // each becomes a tag attribute
  },
})
```

The event arrives in Claude's context wrapped as:

```xml
<channel source="your-channel" key1="val1" key2="val2">event body</channel>
```

## Server options

| Field | Required | Description |
|:------|:---------|:------------|
| `capabilities.experimental['claude/channel']` | Yes | Always `{}`. Registers the listener |
| `capabilities.experimental['claude/channel/permission']` | No | Opt-in to permission relay |
| `capabilities.tools` | Two-way only | Standard MCP tool capability |
| `instructions` | Recommended | Added to Claude's system prompt |

## Gate inbound messages

A channel that listens to a public endpoint is a prompt injection vector.
**Gate on sender identity, not room/chat identity** — `message.from.id`,
not `message.chat.id`.

## Relay permission prompts

Two-way channels can opt in to receive tool approval prompts and relay them
to the user. The local terminal dialog stays open; whichever answer arrives
first is applied.

Notification: `notifications/claude/channel/permission_request`
Verdict back: `notifications/claude/channel/permission` with
`{request_id, behavior: "allow"|"deny"}`

## CortexAgent's relationship

CortexAgent doesn't use channels. Our notifications flow through:

- **Hook events** (`UserPromptSubmit` → cortexagent_call.py → CortexLLM)
- **Daemon control socket** (CLI ↔ daemon)
- **NDJSON streaming** (webui ↔ grammar proxy)

Channels are a future possibility (webhook → daemon → trigger workflow) but
not on the active plan.

## Supported channels (research preview)

- Telegram
- Discord
- iMessage
- fakechat (demo)
- Custom channels require `--dangerously-load-development-channels`
