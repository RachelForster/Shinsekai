use std::{
    fs,
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

use tauri::{
    http::{header, Response, StatusCode},
    AppHandle, Manager, State, Url,
};

use crate::state::{restart_debug_log, DesktopState, BRIDGE_HOST};

pub(crate) const LIVE_FRONTEND_SCHEME: &str = "shinsekai";
pub(crate) const FRONTEND_DIST_MARKER: &str = ".dist-current";
pub(crate) const FRONTEND_DIST_RELEASES: &str = ".dist-releases";

#[tauri::command]
pub(crate) fn desktop_frontend_reload(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    restart_debug_log("desktop_frontend_reload command received");
    reload_live_frontend_windows(&app, state.bridge_port, &state.bridge_auth_token)
}

fn encode_query_value(value: &str) -> String {
    value
        .replace(':', "%3A")
        .replace('/', "%2F")
        .replace(' ', "%20")
        .replace('&', "%26")
        .replace('=', "%3D")
        .replace('#', "%23")
}

fn encode_bridge_url(port: u16) -> String {
    encode_query_value(&format!("http://{BRIDGE_HOST}:{port}"))
}

pub(crate) fn app_window_url_for_route(port: u16, auth_token: &str, route: &str) -> String {
    let encoded = encode_bridge_url(port);
    let encoded_token = encode_query_value(auth_token);
    format!("index.html?shinsekai_bridge={encoded}&shinsekai_bridge_token={encoded_token}#{route}")
}

pub(crate) fn app_window_url(port: u16, auth_token: &str) -> String {
    app_window_url_for_route(port, auth_token, "/settings/api")
}

pub(crate) fn chat_window_url(port: u16, auth_token: &str) -> String {
    app_window_url_for_route(port, auth_token, "/chat-stage")
}

pub(crate) fn live_frontend_origin_for_platform(is_windows: bool) -> String {
    if is_windows {
        format!("http://{LIVE_FRONTEND_SCHEME}.localhost")
    } else {
        format!("{LIVE_FRONTEND_SCHEME}://localhost")
    }
}

pub(crate) fn live_frontend_url_for_route(port: u16, auth_token: &str, route: &str) -> String {
    let encoded = encode_bridge_url(port);
    let encoded_token = encode_query_value(auth_token);
    let origin = live_frontend_origin_for_platform(cfg!(windows));
    let reload_token = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().to_string())
        .unwrap_or_else(|_| "0".to_string());
    format!(
        "{origin}/?shinsekai_bridge={encoded}&shinsekai_bridge_token={encoded_token}&shinsekai_reload={reload_token}#{route}"
    )
}

pub(crate) fn live_frontend_url(port: u16, auth_token: &str) -> String {
    live_frontend_url_for_route(port, auth_token, "/settings/api")
}

pub(crate) fn live_chat_frontend_url(port: u16, auth_token: &str) -> String {
    live_frontend_url_for_route(port, auth_token, "/chat-stage")
}

fn navigate_window_to_live_frontend(
    app: &AppHandle,
    label: &str,
    target_url: &str,
) -> Result<(), String> {
    let url = Url::parse(target_url).map_err(|error| error.to_string())?;
    if let Some(window) = app.get_webview_window(label) {
        restart_debug_log(format!("navigate {label} live frontend url={url}"));
        window.navigate(url).map_err(|error| error.to_string())?;
    }
    Ok(())
}

pub(crate) fn navigate_main_window_to_live_frontend(
    app: &AppHandle,
    bridge_port: u16,
    auth_token: &str,
) -> Result<(), String> {
    navigate_window_to_live_frontend(
        app,
        "reminders",
        &live_frontend_url_for_route(bridge_port, auth_token, "/reminders"),
    )?;
    navigate_window_to_live_frontend(app, "main", &live_frontend_url(bridge_port, auth_token))
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn navigate_chat_window_to_live_frontend(
    app: &AppHandle,
    bridge_port: u16,
    auth_token: &str,
) -> Result<(), String> {
    navigate_window_to_live_frontend(
        app,
        "chat",
        &live_chat_frontend_url(bridge_port, auth_token),
    )
}

pub(crate) fn live_frontend_reload_targets(
    bridge_port: u16,
    auth_token: &str,
) -> [(&'static str, String); 3] {
    [
        ("main", live_frontend_url(bridge_port, auth_token)),
        ("chat", live_chat_frontend_url(bridge_port, auth_token)),
        (
            "reminders",
            live_frontend_url_for_route(bridge_port, auth_token, "/reminders"),
        ),
    ]
}

fn reload_live_frontend_windows(
    app: &AppHandle,
    bridge_port: u16,
    auth_token: &str,
) -> Result<(), String> {
    for (label, target_url) in live_frontend_reload_targets(bridge_port, auth_token) {
        navigate_window_to_live_frontend(app, label, &target_url)?;
    }
    Ok(())
}

pub(crate) fn serve_live_frontend_protocol(
    frontend_dist: &Arc<Mutex<Option<PathBuf>>>,
    request_path: &str,
) -> Response<Vec<u8>> {
    let raw_dist = match frontend_dist.lock().ok().and_then(|dist| dist.clone()) {
        Some(path) => path,
        None => {
            return protocol_text_response(
                StatusCode::SERVICE_UNAVAILABLE,
                "frontend dist is not ready",
            )
        }
    };
    let current_dist = resolve_published_frontend_dist(&raw_dist);
    let index_path = current_dist.join("index.html");
    if !index_path.is_file() {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend index.html not found");
    }

    if request_path.is_empty() || request_path == "/" || request_path == "/index.html" {
        return protocol_file_response(&index_path);
    }

    for root in frontend_dist_roots(&raw_dist) {
        if let Some(candidate) = resolve_static_request_path(&root, request_path) {
            if candidate.is_file() {
                return protocol_file_response(&candidate);
            }
        }
    }

    if request_path.starts_with("/web-assets/") {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend asset not found");
    }
    protocol_file_response(&index_path)
}

pub(crate) fn resolve_published_frontend_dist(raw_dist: &Path) -> PathBuf {
    let Some(frontend_dir) = raw_dist.parent() else {
        return raw_dist.to_path_buf();
    };
    let marker = frontend_dir.join(FRONTEND_DIST_MARKER);
    let Ok(marker_text) = fs::read_to_string(marker) else {
        return raw_dist.to_path_buf();
    };
    let trimmed = marker_text.trim();
    if trimmed.is_empty() {
        return raw_dist.to_path_buf();
    }
    let relative = Path::new(trimmed);
    if relative.is_absolute()
        || !relative
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
    {
        return raw_dist.to_path_buf();
    }

    let frontend_root = frontend_dir
        .canonicalize()
        .unwrap_or_else(|_| frontend_dir.to_path_buf());
    let Ok(target) = frontend_root.join(relative).canonicalize() else {
        return raw_dist.to_path_buf();
    };
    if !target.starts_with(&frontend_root) || !target.join("index.html").is_file() {
        return raw_dist.to_path_buf();
    }
    target
}

fn frontend_dist_roots(raw_dist: &Path) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    push_frontend_dist_root(&mut roots, resolve_published_frontend_dist(raw_dist));
    push_frontend_dist_root(&mut roots, raw_dist.to_path_buf());

    if let Some(frontend_dir) = raw_dist.parent() {
        let releases_dir = frontend_dir.join(FRONTEND_DIST_RELEASES);
        if let Ok(entries) = fs::read_dir(releases_dir) {
            let mut release_dirs = entries
                .filter_map(Result::ok)
                .map(|entry| entry.path())
                .filter(|path| path.is_dir())
                .collect::<Vec<_>>();
            release_dirs.sort_by_key(|path| {
                fs::metadata(path)
                    .and_then(|metadata| metadata.modified())
                    .ok()
                    .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
                    .map(|duration| duration.as_millis())
                    .unwrap_or(0)
            });
            release_dirs.reverse();
            for release_dir in release_dirs {
                push_frontend_dist_root(&mut roots, release_dir);
            }
        }
    }
    roots
}

fn push_frontend_dist_root(roots: &mut Vec<PathBuf>, root: PathBuf) {
    if !root.join("index.html").is_file() {
        return;
    }
    let resolved = root.canonicalize().unwrap_or(root);
    if !roots.iter().any(|candidate| candidate == &resolved) {
        roots.push(resolved);
    }
}

pub(crate) fn resolve_static_request_path(root: &Path, request_path: &str) -> Option<PathBuf> {
    let decoded = percent_decode_path(request_path)?;
    let mut target = root.to_path_buf();
    for part in decoded.trim_start_matches('/').split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." || part.contains('\\') {
            return None;
        }
        target.push(part);
    }
    Some(target)
}

fn percent_decode_path(path: &str) -> Option<String> {
    let bytes = path.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            if index + 2 >= bytes.len() {
                return None;
            }
            let high = hex_value(bytes[index + 1])?;
            let low = hex_value(bytes[index + 2])?;
            out.push((high << 4) | low);
            index += 3;
        } else {
            out.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(out).ok()
}

fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

fn protocol_file_response(path: &Path) -> Response<Vec<u8>> {
    let Ok(body) = fs::read(path) else {
        return protocol_text_response(StatusCode::NOT_FOUND, "frontend file not found");
    };
    let cache_control = if path.file_name().and_then(|name| name.to_str()) == Some("index.html") {
        "no-cache"
    } else {
        "public, max-age=31536000, immutable"
    };
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, content_type_for_path(path))
        .header(header::CACHE_CONTROL, cache_control)
        .body(body)
        .unwrap_or_else(|_| {
            protocol_text_response(StatusCode::INTERNAL_SERVER_ERROR, "response build failed")
        })
}

fn protocol_text_response(status: StatusCode, message: &str) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .body(message.as_bytes().to_vec())
        .unwrap_or_else(|_| Response::new(Vec::new()))
}

fn content_type_for_path(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| extension.to_ascii_lowercase())
        .as_deref()
    {
        Some("html") => "text/html; charset=utf-8",
        Some("js") | Some("mjs") => "text/javascript; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        Some("json") => "application/json; charset=utf-8",
        Some("svg") => "image/svg+xml",
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        Some("ico") => "image/x-icon",
        Some("woff") => "font/woff",
        Some("woff2") => "font/woff2",
        Some("ttf") => "font/ttf",
        Some("wasm") => "application/wasm",
        _ => "application/octet-stream",
    }
}
