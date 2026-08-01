use crate::mcp::{McpServer, ToolDefinition};
use serde_json::json;
use std::collections::HashMap;

/// Configuration for an MCP server subprocess
#[derive(Clone)]
pub struct McpServerConfig {
    pub name: String,
    pub command: String,
    pub args: Vec<String>,
    pub tools: Vec<ToolDefinition>,
}

/// Build the default set of MCP servers
pub fn default_mcp_servers() -> Vec<McpServerConfig> {
    let mut servers = Vec::new();

    // Filesystem MCP server (Read/Write/Edit)
    servers.push(McpServerConfig {
        name: "filesystem".into(),
        command: "npx".into(),
        args: vec![
            "-y".into(),
            "@modelcontextprotocol/server-filesystem".into(),
            "/".into(),
        ],
        tools: vec![
            ToolDefinition {
                name: "read_file".into(),
                description: "Read a file from the filesystem".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the file"}
                    },
                    "required": ["path"]
                })),
            },
            ToolDefinition {
                name: "write_file".into(),
                description: "Write content to a file".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the file"},
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["path", "content"]
                })),
            },
            ToolDefinition {
                name: "edit_file".into(),
                description: "Edit a file by replacing text".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the file"},
                        "old_string": {"type": "string", "description": "Text to replace"},
                        "new_string": {"type": "string", "description": "Replacement text"}
                    },
                    "required": ["path", "old_string", "new_string"]
                })),
            },
        ],
    });

    // Bash MCP server
    servers.push(McpServerConfig {
        name: "bash".into(),
        command: "npx".into(),
        args: vec![
            "-y".into(),
            "@modelcontextprotocol/server-bash".into(),
        ],
        tools: vec![
            ToolDefinition {
                name: "bash".into(),
                description: "Execute a shell command".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"}
                    },
                    "required": ["command"]
                })),
            },
        ],
    });

    // WebFetch MCP server
    servers.push(McpServerConfig {
        name: "fetch".into(),
        command: "npx".into(),
        args: vec![
            "-y".into(),
            "@modelcontextprotocol/server-fetch".into(),
        ],
        tools: vec![
            ToolDefinition {
                name: "fetch".into(),
                description: "Fetch a URL and return its content".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"}
                    },
                    "required": ["url"]
                })),
            },
        ],
    });

    // WebSearch MCP server (Brave Search)
    servers.push(McpServerConfig {
        name: "websearch".into(),
        command: "npx".into(),
        args: vec![
            "-y".into(),
            "@modelcontextprotocol/server-brave-search".into(),
        ],
        tools: vec![
            ToolDefinition {
                name: "web_search".into(),
                description: "Search the web using Brave Search".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                })),
            },
        ],
    });

    // Puppeteer MCP server (browser automation)
    servers.push(McpServerConfig {
        name: "puppeteer".into(),
        command: "npx".into(),
        args: vec![
            "-y".into(),
            "@modelcontextprotocol/server-puppeteer".into(),
        ],
        tools: vec![
            ToolDefinition {
                name: "browser_navigate".into(),
                description: "Navigate to a URL in the browser".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"}
                    },
                    "required": ["url"]
                })),
            },
            ToolDefinition {
                name: "browser_screenshot".into(),
                description: "Take a screenshot of the current page".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {}
                })),
            },
            ToolDefinition {
                name: "browser_click".into(),
                description: "Click an element on the page".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector for the element"}
                    },
                    "required": ["selector"]
                })),
            },
            ToolDefinition {
                name: "browser_type".into(),
                description: "Type text into an element".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector for the element"},
                        "text": {"type": "string", "description": "Text to type"}
                    },
                    "required": ["selector", "text"]
                })),
            },
        ],
    });

    // Chat tool — handled directly by the tray app (not an MCP server subprocess)
    // The tray app spawns `claude -p "<message>"` to get responses.
    servers.push(McpServerConfig {
        name: "chat".into(),
        command: "claude".into(),  // placeholder — handled specially in mcp.rs
        args: vec![],
        tools: vec![
            ToolDefinition {
                name: "chat".into(),
                description: "Send a chat message to the AI agent. The agent has access to Bash, filesystem, web search, and browser tools.".into(),
                input_schema: Some(json!({
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "The user's message or question"},
                        "context": {"type": "string", "description": "Optional page context from the browser"}
                    },
                    "required": ["message"]
                })),
            },
        ],
    });

    servers
}

/// Register all default MCP servers into the router
pub fn register_default_servers(router: &mut crate::mcp::McpRouter) {
    for config in default_mcp_servers() {
        router.register_server(McpServer {
            name: config.name,
            tools: config.tools,
            command: config.command,
            args: config.args,
        });
    }
}
