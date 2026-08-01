use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;

/// JSON-RPC 2.0 request
#[derive(Deserialize)]
pub struct JsonRpcRequest {
    pub jsonrpc: String,
    pub method: String,
    pub id: Option<Value>,
    pub params: Option<Value>,
}

/// JSON-RPC 2.0 response
#[derive(Serialize)]
pub struct JsonRpcResponse {
    pub jsonrpc: String,
    pub id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<JsonRpcError>,
}

#[derive(Serialize)]
pub struct JsonRpcError {
    pub code: i32,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

/// Tool definition (MCP wire format)
#[derive(Clone, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_schema: Option<Value>,
}

/// Registered MCP server
#[derive(Clone)]
pub struct McpServer {
    pub name: String,
    pub tools: Vec<ToolDefinition>,
    pub command: String,
    pub args: Vec<String>,
}

/// MCP router state
pub struct McpRouter {
    servers: Vec<McpServer>,
}

impl McpRouter {
    pub fn new() -> Self {
        McpRouter {
            servers: Vec::new(),
        }
    }

    pub fn register_server(&mut self, server: McpServer) {
        self.servers.push(server);
    }

    pub fn list_tools(&self) -> Vec<ToolDefinition> {
        let mut all_tools = Vec::new();
        for server in &self.servers {
            all_tools.extend(server.tools.clone());
        }
        all_tools
    }

    pub fn find_server_for_tool(&self, tool_name: &str) -> Option<&McpServer> {
        for server in &self.servers {
            if server.tools.iter().any(|t| t.name == tool_name) {
                return Some(server);
            }
        }
        None
    }

    pub async fn call_tool(&self, tool_name: &str, args: Value) -> Result<Value, String> {
        // Special case: "chat" tool — spawns claude directly, not an MCP server
        if tool_name == "chat" {
            return self.call_chat(args).await;
        }

        let server = self
            .find_server_for_tool(tool_name)
            .ok_or_else(|| format!("tool '{}' not found", tool_name))?;

        // Build the MCP JSON-RPC call for the subprocess
        let call = json!({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args
            },
            "id": 1
        });

        // Spawn the MCP server subprocess and send the request via stdin
        let output = tokio::process::Command::new(&server.command)
            .args(&server.args)
            .arg("--json")
            .arg(serde_json::to_string(&call).unwrap_or_default())
            .output()
            .await
            .map_err(|e| format!("failed to run MCP server '{}': {}", server.name, e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("MCP server '{}' failed: {}", server.name, stderr));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let response: Value =
            serde_json::from_str(&stdout).map_err(|e| format!("invalid MCP response: {}", e))?;

        Ok(response)
    }

    /// Handle the "chat" tool — spawns claude CLI to get a response
    async fn call_chat(&self, args: Value) -> Result<Value, String> {
        let message = args
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        if message.is_empty() {
            return Err("message is required".into());
        }

        println!("\n─────────────────────────────────────────────────────────────────");
        println!("[cortexagent] Processing: {}", &message[..message.len().min(80)]);

        // Use claude -p with stream-json for the web UI
        // Use full path to avoid PATH issues when spawned from desktop
        let claude_path = std::env::var("CORTEXAGENT_CLI")
            .unwrap_or_else(|_| "claude".into());
        let output = tokio::process::Command::new(&claude_path)
            .args(["-p", &message, "--output-format", "stream-json"])
            .output()
            .await
            .map_err(|e| format!("failed to run agent: {}", e))?;

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();

        if !output.status.success() {
            let err_msg = if stderr.is_empty() { "unknown error".to_string() } else { stderr.clone() };
            return Err(format!("agent exited with code {}: {}", output.status.code().unwrap_or(-1), err_msg));
        }

        // Parse the JSON stream to extract thinking, tool calls, and final response
        let mut response_parts: Vec<String> = Vec::new();
        let mut final_result = String::new();
        let mut usage_data: Option<Value> = None;
        let mut duration_ms: u64 = 0;

        for line in stdout.lines() {
            if let Ok(event) = serde_json::from_str::<Value>(line) {
                let event_type = event.get("type").and_then(|v| v.as_str()).unwrap_or("");
                match event_type {
                    "assistant" => {
                        if let Some(content) = event.pointer("/message/content") {
                            if let Some(arr) = content.as_array() {
                                for item in arr {
                                    let ctype = item.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                    match ctype {
                                        "thinking" => {
                                            if let Some(text) = item.get("thinking").and_then(|v| v.as_str()) {
                                                println!("[cortexagent] 🤔 Thinking: {}...", &text[..text.len().min(120)]);
                                            }
                                        }
                                        "text" => {
                                            if let Some(text) = item.get("text").and_then(|v| v.as_str()) {
                                                response_parts.push(text.to_string());
                                            }
                                        }
                                        "tool_use" => {
                                            if let Some(name) = item.get("name").and_then(|v| v.as_str()) {
                                                println!("[cortexagent] 🔧 Tool call: {}", name);
                                            }
                                        }
                                        _ => {}
                                    }
                                }
                            }
                        }
                    }
                    "result" => {
                        if let Some(result) = event.get("result").and_then(|v| v.as_str()) {
                            final_result = result.to_string();
                        }
                        if let Some(usage) = event.get("usage") {
                            usage_data = Some(usage.clone());
                        }
                        if let Some(dur) = event.get("duration_ms").and_then(|v| v.as_u64()) {
                            duration_ms = dur;
                        }
                    }
                    _ => {}
                }
            }
        }

        let response_text = if !response_parts.is_empty() {
            response_parts.join("")
        } else if !final_result.is_empty() {
            final_result
        } else {
            stdout
        };

        let input_tok = usage_data.as_ref().and_then(|u| u.get("input_tokens")).and_then(|v| v.as_u64()).unwrap_or(0);
        let output_tok = usage_data.as_ref().and_then(|u| u.get("output_tokens")).and_then(|v| v.as_u64()).unwrap_or(0);
        println!("[cortexagent] ✅ Response ({} in / {} out / {} ms)", input_tok, output_tok, duration_ms);
        println!("─────────────────────────────────────────────────────────────────\n");

        let mut response = json!({
            "content": [{
                "type": "text",
                "text": response_text
            }]
        });

        if let Some(ref usage) = usage_data {
            response["usage"] = usage.clone();
        }
        response["duration_ms"] = json!(duration_ms);
        response["input_tokens"] = json!(input_tok);
        response["output_tokens"] = json!(output_tok);

        Ok(response)
    }
}

/// Handle a JSON-RPC request
pub async fn handle_request(router: &Arc<Mutex<McpRouter>>, request: JsonRpcRequest) -> JsonRpcResponse {
    let id = request.id.clone();

    match request.method.as_str() {
        "tools/list" => {
            let router = router.lock().await;
            let tools = router.list_tools();
            JsonRpcResponse {
                jsonrpc: "2.0".into(),
                id,
                result: Some(json!({ "tools": tools })),
                error: None,
            }
        }
        "tools/call" => {
            let params = request.params.unwrap_or(json!({}));
            let tool_name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let args = params.get("arguments").cloned().unwrap_or(json!({}));

            let router = router.lock().await;
            match router.call_tool(tool_name, args).await {
                Ok(result) => JsonRpcResponse {
                    jsonrpc: "2.0".into(),
                    id,
                    result: Some(result),
                    error: None,
                },
                Err(e) => JsonRpcResponse {
                    jsonrpc: "2.0".into(),
                    id,
                    result: None,
                    error: Some(JsonRpcError {
                        code: -32000,
                        message: e,
                        data: None,
                    }),
                },
            }
        }
        _ => JsonRpcResponse {
            jsonrpc: "2.0".into(),
            id,
            result: None,
            error: Some(JsonRpcError {
                code: -32601,
                message: format!("method '{}' not found", request.method),
                data: None,
            }),
        },
    }
}

/// Parse a JSON-RPC request from a string
pub fn parse_request(input: &str) -> Result<JsonRpcRequest, String> {
    serde_json::from_str::<JsonRpcRequest>(input)
        .map_err(|e| format!("invalid JSON-RPC request: {}", e))
}

/// Serialize a JSON-RPC response to a string
pub fn serialize_response(response: &JsonRpcResponse) -> String {
    serde_json::to_string(response).unwrap_or_default()
}
