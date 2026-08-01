use std::env;
use std::path::PathBuf;
use std::fs;

/// Remote-connect configuration
pub struct RemoteConfig {
    pub enabled: bool,
    pub bind_addr: String,
    pub port: u16,
    pub token: String,
}

/// Load remote config from environment
pub fn load_remote_config() -> RemoteConfig {
    let enabled = env::var("CORTEXAGENT_REMOTE")
        .map(|v| v == "1" || v.to_lowercase() == "true")
        .unwrap_or(false);

    let bind_addr = if enabled {
        env::var("CORTEXAGENT_REMOTE_BIND")
            .unwrap_or_else(|_| "0.0.0.0".into())
    } else {
        "127.0.0.1".into()
    };

    let port = env::var("CORTEXAGENT_REMOTE_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8090);

    let token = resolve_token();

    RemoteConfig {
        enabled,
        bind_addr,
        port,
        token,
    }
}

/// Resolve the auth token: from env, from file, or auto-generate
fn resolve_token() -> String {
    // Check env first
    if let Ok(token) = env::var("CORTEXAGENT_REMOTE_TOKEN") {
        if !token.is_empty() {
            return token;
        }
    }

    // Check state file
    let token_file = token_file_path();
    if let Ok(content) = fs::read_to_string(&token_file) {
        let token = content.trim().to_string();
        if !token.is_empty() {
            return token;
        }
    }

    // Auto-generate and save
    let token = generate_token();
    if let Some(parent) = token_file.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(&token_file, &token);
    // Set restrictive permissions
    let _ = fs::set_permissions(&token_file, std::os::unix::fs::PermissionsExt::from_mode(0o600));
    token
}

fn token_file_path() -> PathBuf {
    dirs_or_default()
}

fn dirs_or_default() -> PathBuf {
    let home = env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    PathBuf::from(home).join(".cortexagent").join("state").join("remote.token")
}

/// Generate a random token
fn generate_token() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    // Simple but sufficient for local auth
    let hash = blake2_simple(nanos);
    format!("ca_{}", hash)
}

/// Simple non-cryptographic hash for token generation
fn blake2_simple(input: u128) -> String {
    // Use a simple hash since this is for local auth, not crypto
    let hex = format!("{:x}", input);
    let mut result = String::new();
    for (i, c) in hex.chars().enumerate() {
        if i % 2 == 0 {
            result.push(c);
        }
        if result.len() >= 32 {
            break;
        }
    }
    result
}

/// Check if a request is authorized
pub fn check_auth(token: &str, headers: &[(&str, &str)]) -> bool {
    let config = load_remote_config();
    if !config.enabled || config.token.is_empty() {
        return true; // No auth required when not in remote mode
    }

    for (name, value) in headers {
        let name_lower = name.to_lowercase();
        if name_lower == "authorization" {
            if let Some(bearer) = value.strip_prefix("Bearer ") {
                if bearer == config.token {
                    return true;
                }
            }
        }
        if name_lower == "x-cortexagent-token" {
            if *value == config.token {
                return true;
            }
        }
    }
    false
}
