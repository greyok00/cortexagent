mod mcp;
mod remote;
mod subprocess;

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use futures_util::{SinkExt, StreamExt};
use mcp::McpRouter;
use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex;
use tower_http::cors::CorsLayer;

/// Shared application state
struct AppState {
    mcp_router: Arc<Mutex<McpRouter>>,
}

/// Auth middleware: check token for remote requests
fn check_auth(headers: &HeaderMap) -> Result<(), StatusCode> {
    let config = remote::load_remote_config();
    if !config.enabled || config.token.is_empty() {
        return Ok(()); // No auth required when not in remote mode
    }

    // Check Authorization header
    if let Some(auth) = headers.get("authorization") {
        if let Ok(value) = auth.to_str() {
            if let Some(bearer) = value.strip_prefix("Bearer ") {
                if bearer == config.token {
                    return Ok(());
                }
            }
        }
    }

    // Check X-CortexAgent-Token header
    if let Some(token) = headers.get("x-cortexagent-token") {
        if let Ok(value) = token.to_str() {
            if value == config.token {
                return Ok(());
            }
        }
    }

    Err(StatusCode::UNAUTHORIZED)
}

/// GET / — serve the chat HTML
async fn index_html() -> impl IntoResponse {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("ui")
        .join("index.html");
    match tokio::fs::read_to_string(&path).await {
        Ok(html) => (
            StatusCode::OK,
            [("Content-Type", "text/html; charset=utf-8")],
            html,
        ),
        Err(_) => (
            StatusCode::NOT_FOUND,
            [("Content-Type", "text/plain")],
            "index.html not found".to_string(),
        ),
    }
}

/// GET /health
async fn health() -> impl IntoResponse {
    Json(serde_json::json!({
        "ok": true,
        "service": "cortexagent-tray"
    }))
}

/// GET /mcp/tools — list all available tools
async fn list_tools(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> impl IntoResponse {
    if let Err(status) = check_auth(&headers) {
        return (status, Json(serde_json::json!({ "error": "unauthorized" })));
    }
    let router = state.mcp_router.lock().await;
    let tools = router.list_tools();
    (StatusCode::OK, Json(serde_json::json!({ "tools": tools })))
}

/// POST /mcp/call — call a tool
async fn call_tool(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    if let Err(status) = check_auth(&headers) {
        return (status, Json(serde_json::json!({ "error": "unauthorized" })));
    }
    let tool_name = body
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let args = body.get("arguments").cloned().unwrap_or(serde_json::json!({}));

    let router = state.mcp_router.lock().await;
    match router.call_tool(tool_name, args).await {
        Ok(result) => (StatusCode::OK, Json(serde_json::json!({ "ok": true, "result": result }))),
        Err(e) => (StatusCode::OK, Json(serde_json::json!({ "ok": false, "error": e }))),
    }
}

/// POST /mcp — JSON-RPC 2.0 endpoint
async fn mcp_rpc(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<serde_json::Value>,
) -> impl IntoResponse {
    if let Err(status) = check_auth(&headers) {
        return (status, Json(serde_json::json!({ "error": "unauthorized" })));
    }
    let method = body.get("method").and_then(|v| v.as_str()).unwrap_or("");
    let id = body.get("id").cloned();

    match method {
        "tools/list" => {
            let router = state.mcp_router.lock().await;
            let tools = router.list_tools();
            (StatusCode::OK, Json(serde_json::json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": { "tools": tools }
            })))
        }
        "tools/call" => {
            let params = body.get("params").cloned().unwrap_or(serde_json::json!({}));
            let tool_name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let args = params.get("arguments").cloned().unwrap_or(serde_json::json!({}));

            let router = state.mcp_router.lock().await;
            match router.call_tool(tool_name, args).await {
                Ok(result) => (StatusCode::OK, Json(serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": result
                }))),
                Err(e) => (StatusCode::OK, Json(serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": { "code": -32000, "message": e }
                }))),
            }
        }
        _ => (StatusCode::OK, Json(serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": { "code": -32601, "message": format!("method '{}' not found", method) }
        }))),
    }
}

/// WebSocket handler — accepts JSON-RPC messages over WebSocket
async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_ws(socket, state))
}

async fn handle_ws(socket: WebSocket, state: Arc<AppState>) {
    let (mut sender, mut receiver) = socket.split();
    while let Some(Ok(msg)) = receiver.next().await {
        if let Message::Text(text) = msg {
            // Parse JSON-RPC request
            if let Ok(request) = serde_json::from_str::<mcp::JsonRpcRequest>(&text) {
                let response = mcp::handle_request(&state.mcp_router, request).await;
                let json = mcp::serialize_response(&response);
                let _ = sender.send(Message::Text(json.into())).await;
            } else {
                let err = serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": null,
                    "error": { "code": -32700, "message": "parse error" }
                });
                let _ = sender.send(Message::Text(err.to_string().into())).await;
            }
        }
    }
}

/// Start the MCP HTTP server
async fn start_mcp_server(state: Arc<AppState>) {
    let app = Router::new()
        .route("/", get(index_html))
        .route("/health", get(health))
        .route("/mcp/tools", get(list_tools))
        .route("/mcp/call", post(call_tool))
        .route("/mcp", get(ws_handler).post(mcp_rpc))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let config = remote::load_remote_config();
    let addr = format!("{}:{}", config.bind_addr, config.port);

    if config.enabled {
        println!("[cortexagent] REMOTE MODE ENABLED — MCP server on http://{}", addr);
        println!("[cortexagent] Auth token: {}", config.token);
        println!("[cortexagent] Connect from extension settings: host={}:{} token={}",
                 config.bind_addr, config.port, config.token);
    } else {
        println!("[cortexagent] MCP server listening on http://{}", addr);
    }

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Create a Tokio runtime for the MCP server
    let rt = tokio::runtime::Runtime::new().expect("failed to create Tokio runtime");

    // Build the MCP router with default servers
    let mut router = McpRouter::new();
    subprocess::register_default_servers(&mut router);

    let state = Arc::new(AppState {
        mcp_router: Arc::new(Mutex::new(router)),
    });

    // Start the MCP server on the Tokio runtime
    let mcp_state = state.clone();
    let _enter = rt.enter();
    tokio::spawn(async move {
        start_mcp_server(mcp_state).await;
    });

    // ── Start llama-server (if not already running) ──
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    let llama_binary = format!("{}/llama.cpp/build/bin/llama-server", home);
    let model = std::env::var("CORTEXAGENT_MODEL").unwrap_or_else(|_|
        format!("{}/models/qwen3.6-35b-iq3s/Qwen3.6-35B-A3B-UD-IQ3_S.gguf", home));
    if std::path::Path::new(&llama_binary).exists() && std::path::Path::new(&model).exists() {
        let port_busy = std::process::Command::new("ss")
            .args(["-ltn"])
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).contains(":8080 "))
            .unwrap_or(false);
        if !port_busy {
            println!("[cortexagent] Starting llama-server...");
            let log = format!("{}/.cortexagent/logs/llama-server.log", home);
            std::fs::create_dir_all(format!("{}/.cortexagent/logs", home)).ok();
            let _llama = std::process::Command::new("bash")
                .arg("-c")
                .arg(format!(
                    "nohup '{}' -m '{}' -c 262144 -ngl 999 -fa on -ctk q8_0 -ctv q8_0 -np 1 --no-kv-offload --kv-unified --host 127.0.0.1 --port 8080 > '{}' 2>&1 &",
                    llama_binary, model, log
                ))
                .spawn();
            for _ in 0..30 {
                std::thread::sleep(std::time::Duration::from_secs(1));
                if std::process::Command::new("ss").args(["-ltn"]).output()
                    .map(|o| String::from_utf8_lossy(&o.stdout).contains(":8080 ")).unwrap_or(false) {
                    println!("[cortexagent] llama-server ready");
                    break;
                }
            }
        } else {
            println!("[cortexagent] llama-server already running");
        }
    }

    // Note: The CLI (cortexagent) runs independently. The web UI uses claude -p
    // for one-shot queries. They share llama-server but not the same session.

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Build tray menu
            let open = tauri::menu::MenuItem::with_id(app, "open", "Open CortexAgent", true, None::<&str>)?;
            let quit = tauri::menu::MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = tauri::menu::Menu::with_items(app, &[&open, &quit])?;

            // Build tray icon
            let _tray = tauri::tray::TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .tooltip("CortexAgent")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => {
                        use tauri_plugin_shell::ShellExt;
                        let _ = app.shell().open("http://127.0.0.1:8090/", None);
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| match event {
                    tauri::tray::TrayIconEvent::Click {
                        button: tauri::tray::MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } => {
                        let app = tray.app_handle();
                        use tauri_plugin_shell::ShellExt;
                        let _ = app.shell().open("http://127.0.0.1:8090/", None);
                    }
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running CortexAgent tray");
}
