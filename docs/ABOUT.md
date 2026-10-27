CortexAgent is a minimal agent harness that runs entirely on your own computer: a reasoning loop, one memory file, token compression, and a control socket. There is nothing else in the core. It is a hard fork of pi.dev, reshaped for fully-local, single-machine use.

The core provides nine built-in tools (shell, web fetch, document parsing, memory search, subagents, and more) and connects to external MCP servers for anything beyond that: Chrome control and a web-scraping proxy are installed by default, and additional servers are configured in mcp.json and sleep until used.

The design is local by default. The agent talks to a llama.cpp server bound to 127.0.0.1:11599; memory is a single append-friendly NJSON file rather than a database or a background daemon; and compression rewrites conversation history and tool output before the model sees them, which is how a small local model carries long sessions. Tools arrive only through MCP servers you install from their own repos and point the config at — CortexAgent is a client only, and a server wakes lazily the first time one of its tools is called. A single control socket and systemd user units handle lifecycle, so there is one clearly defined way to start, stop, and query the daemon.

Everything you see on screen is one fixed-height status line showing runtime phase, compression savings, and memory state. Work and retry states share that row and never add height.

This is for people who run their own box and want the loop, not a platform — the ones who point their config at the servers they trust and expect the logs to remain on their own machine.

Licensed under the Apache License 2.0.