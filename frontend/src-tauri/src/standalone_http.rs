use std::{
    collections::{HashMap, VecDeque},
    sync::{Mutex, OnceLock},
    time::Duration,
};

use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use serde::{Deserialize, Serialize};

pub const HTTP_ABORTED_PREFIX: &str = "HTTP_ABORTED:";
const MAX_PRE_CANCELLED: usize = 256;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StandaloneHttpRequest {
    #[serde(default)]
    pub request_id: Option<String>,
    pub url: String,
    pub method: String,
    #[serde(default)]
    pub headers: HashMap<String, String>,
    pub body_base64: Option<String>,
    pub timeout_ms: Option<u64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StandaloneHttpResponse {
    pub status: u16,
    pub headers: HashMap<String, String>,
    pub body_base64: String,
}

const B64_TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn base64_encode(input: &[u8]) -> String {
    let mut out = String::with_capacity(input.len().div_ceil(3) * 4);
    for chunk in input.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        let triple = (b0 << 16) | (b1 << 8) | b2;
        out.push(B64_TABLE[((triple >> 18) & 0x3f) as usize] as char);
        out.push(B64_TABLE[((triple >> 12) & 0x3f) as usize] as char);
        out.push(if chunk.len() > 1 {
            B64_TABLE[((triple >> 6) & 0x3f) as usize] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            B64_TABLE[(triple & 0x3f) as usize] as char
        } else {
            '='
        });
    }
    out
}

fn decode_char(byte: u8) -> Option<u8> {
    match byte {
        b'A'..=b'Z' => Some(byte - b'A'),
        b'a'..=b'z' => Some(byte - b'a' + 26),
        b'0'..=b'9' => Some(byte - b'0' + 52),
        b'+' | b'-' => Some(62),
        b'/' | b'_' => Some(63),
        _ => None,
    }
}

fn base64_decode(input: &str) -> Result<Vec<u8>, String> {
    let bytes: Vec<u8> = input
        .bytes()
        .filter(|b| !b.is_ascii_whitespace())
        .collect();
    if bytes.is_empty() {
        return Ok(Vec::new());
    }
    if bytes.len() % 4 != 0 {
        return Err("Invalid base64 payload length".to_string());
    }
    let mut out = Vec::with_capacity((bytes.len() / 4) * 3);
    for quad in bytes.chunks_exact(4) {
        let c0 = decode_char(quad[0]).ok_or_else(|| "Invalid base64 character".to_string())? as u32;
        let c1 = decode_char(quad[1]).ok_or_else(|| "Invalid base64 character".to_string())? as u32;
        let c2 = if quad[2] == b'=' {
            None
        } else {
            Some(decode_char(quad[2]).ok_or_else(|| "Invalid base64 character".to_string())? as u32)
        };
        let c3 = if quad[3] == b'=' {
            None
        } else {
            Some(decode_char(quad[3]).ok_or_else(|| "Invalid base64 character".to_string())? as u32)
        };

        let val = (c0 << 18) | (c1 << 12) | (c2.unwrap_or(0) << 6) | c3.unwrap_or(0);
        out.push(((val >> 16) & 0xff) as u8);
        if c2.is_some() {
            out.push(((val >> 8) & 0xff) as u8);
        }
        if c3.is_some() {
            out.push((val & 0xff) as u8);
        }
    }
    Ok(out)
}

static SHARED_CLIENT: OnceLock<Result<reqwest::Client, String>> = OnceLock::new();
static IN_FLIGHT_REGISTRY: OnceLock<Mutex<InFlightRegistry>> = OnceLock::new();

#[derive(Default)]
struct InFlightRegistry {
    active: HashMap<String, tauri::async_runtime::JoinHandle<()>>,
    pre_cancelled: VecDeque<String>,
}

impl InFlightRegistry {
    fn take_pre_cancelled(&mut self, request_id: &str) -> bool {
        if let Some(pos) = self.pre_cancelled.iter().position(|id| id == request_id) {
            self.pre_cancelled.remove(pos);
            true
        } else {
            false
        }
    }

    fn push_pre_cancelled(&mut self, request_id: String) {
        if !self.pre_cancelled.iter().any(|id| id == &request_id) {
            if self.pre_cancelled.len() >= MAX_PRE_CANCELLED {
                self.pre_cancelled.pop_front();
            }
            self.pre_cancelled.push_back(request_id);
        }
    }
}

fn registry() -> &'static Mutex<InFlightRegistry> {
    IN_FLIGHT_REGISTRY.get_or_init(|| Mutex::new(InFlightRegistry::default()))
}

fn shared_http_client() -> Result<&'static reqwest::Client, String> {
    let entry = SHARED_CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .build()
            .map_err(|err| format!("Failed to construct HTTP client: {err}"))
    });
    match entry {
        Ok(client) => Ok(client),
        Err(err) => Err(err.clone()),
    }
}

struct ActiveRequestGuard {
    request_id: Option<String>,
}

impl ActiveRequestGuard {
    fn disarm(&mut self) {
        if let Some(id) = self.request_id.take() {
            if let Ok(mut reg) = registry().lock() {
                reg.active.remove(&id);
            }
        }
    }
}

impl Drop for ActiveRequestGuard {
    fn drop(&mut self) {
        if let Some(id) = self.request_id.take() {
            if let Ok(mut reg) = registry().lock() {
                if let Some(handle) = reg.active.remove(&id) {
                    handle.abort();
                }
            }
        }
    }
}

async fn execute_http_request(request: StandaloneHttpRequest) -> Result<StandaloneHttpResponse, String> {
    let parsed_method = reqwest::Method::from_bytes(request.method.trim().as_bytes())
        .map_err(|err| format!("Invalid HTTP method: {err}"))?;

    let timeout = Duration::from_millis(request.timeout_ms.unwrap_or(60_000).clamp(1_000, 180_000));
    let client = shared_http_client()?;

    let mut header_map = HeaderMap::new();
    for (k, v) in request.headers {
        let lower = k.trim().to_ascii_lowercase();
        if lower == "host" || lower == "content-length" || lower == "connection" {
            continue;
        }
        if let (Ok(name), Ok(value)) = (
            HeaderName::from_bytes(lower.as_bytes()),
            HeaderValue::from_str(&v),
        ) {
            header_map.insert(name, value);
        }
    }

    let mut req_builder = client
        .request(parsed_method.clone(), &request.url)
        .timeout(timeout)
        .headers(header_map);
    if parsed_method != reqwest::Method::GET && parsed_method != reqwest::Method::HEAD {
        if let Some(b64) = request.body_base64 {
            let body_bytes = base64_decode(&b64)?;
            req_builder = req_builder.body(body_bytes);
        }
    }

    let response = req_builder
        .send()
        .await
        .map_err(|err| format!("Network request failed: {err}"))?;
    let status = response.status().as_u16();
    let mut resp_headers = HashMap::new();
    for (k, v) in response.headers() {
        if let Ok(val_str) = v.to_str() {
            resp_headers.insert(k.as_str().to_ascii_lowercase(), val_str.to_string());
        }
    }
    let body_bytes = response
        .bytes()
        .await
        .map_err(|err| format!("Failed to read HTTP response body: {err}"))?;

    Ok(StandaloneHttpResponse {
        status,
        headers: resp_headers,
        body_base64: base64_encode(&body_bytes),
    })
}

fn aborted_error() -> String {
    format!("{HTTP_ABORTED_PREFIX} The operation was aborted.")
}

fn cancel_in_flight_request(request_id: &str) -> bool {
    let trimmed = request_id.trim();
    if trimmed.is_empty() {
        return false;
    }
    if let Ok(mut reg) = registry().lock() {
        if let Some(handle) = reg.active.remove(trimmed) {
            handle.abort();
            return true;
        }
        reg.push_pre_cancelled(trimmed.to_string());
    }
    false
}

#[tauri::command]
pub async fn standalone_http_request(
    request: StandaloneHttpRequest,
) -> Result<StandaloneHttpResponse, String> {
    let request_id = request
        .request_id
        .as_deref()
        .map(str::trim)
        .filter(|id| !id.is_empty())
        .map(str::to_string);

    let Some(id) = request_id else {
        return execute_http_request(request).await;
    };

    let mut result_rx = {
        let mut reg = registry()
            .lock()
            .map_err(|_| "HTTP cancellation registry poisoned".to_string())?;
        if reg.take_pre_cancelled(&id) {
            return Err(aborted_error());
        }

        let (result_tx, result_rx) = tauri::async_runtime::channel(1);
        let handle = tauri::async_runtime::spawn(async move {
            let outcome = execute_http_request(request).await;
            let _ = result_tx.send(outcome).await;
        });
        if let Some(prev) = reg.active.insert(id.clone(), handle) {
            prev.abort();
        }
        result_rx
    };

    let mut guard = ActiveRequestGuard {
        request_id: Some(id),
    };
    let outcome = result_rx.recv().await;
    guard.disarm();
    match outcome {
        Some(res) => res,
        None => Err(aborted_error()),
    }
}

#[tauri::command]
pub async fn standalone_http_cancel(request_id: String) -> Result<bool, String> {
    Ok(cancel_in_flight_request(&request_id))
}

#[cfg(test)]
mod tests {
    use std::{
        io::{ErrorKind, Read, Write},
        net::TcpListener,
        sync::mpsc,
        time::Duration,
    };

    use super::*;

    fn test_request(url: String, request_id: &str) -> StandaloneHttpRequest {
        StandaloneHttpRequest {
            request_id: Some(request_id.to_string()),
            url,
            method: "GET".to_string(),
            headers: HashMap::new(),
            body_base64: None,
            timeout_ms: Some(30_000),
        }
    }

    #[test]
    fn aborts_in_flight_request_and_closes_socket() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind loopback");
        let addr = listener.local_addr().expect("local addr");
        let (connected_tx, connected_rx) = mpsc::channel();
        let (disconnected_tx, disconnected_rx) = mpsc::channel();

        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
            let mut req_buf = Vec::new();
            let mut chunk = [0u8; 256];
            while !req_buf.windows(4).any(|w| w == b"\r\n\r\n") {
                match stream.read(&mut chunk) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => req_buf.extend_from_slice(&chunk[..n]),
                }
            }
            let _ = stream.write_all(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n");
            let _ = stream.flush();
            let _ = connected_tx.send(());

            loop {
                match stream.read(&mut chunk) {
                    Ok(0) => {
                        let _ = disconnected_tx.send(());
                        break;
                    }
                    Ok(_) => continue,
                    Err(err)
                        if err.kind() == ErrorKind::WouldBlock
                            || err.kind() == ErrorKind::TimedOut =>
                    {
                        break;
                    }
                    Err(_) => {
                        let _ = disconnected_tx.send(());
                        break;
                    }
                }
            }
        });

        tauri::async_runtime::block_on(async move {
            let url = format!("http://{addr}/slow-stream");
            let handle = tauri::async_runtime::spawn(standalone_http_request(test_request(
                url,
                "cancel-live-1",
            )));

            connected_rx
                .recv_timeout(Duration::from_secs(2))
                .expect("client connected and received response head");

            let cancelled = standalone_http_cancel("cancel-live-1".to_string())
                .await
                .expect("cancel command result");
            assert!(cancelled);

            let res = handle.await.expect("join standalone_http_request");
            let err = res.expect_err("request should abort");
            assert!(
                err.starts_with(HTTP_ABORTED_PREFIX),
                "unexpected error message: {err}"
            );

            disconnected_rx
                .recv_timeout(Duration::from_secs(2))
                .expect("socket should close promptly after abort");
        });

        let _ = server.join();
    }

    #[test]
    fn honors_pre_cancellation_before_request_starts() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind loopback");
        listener.set_nonblocking(true).expect("nonblocking");
        let addr = listener.local_addr().expect("local addr");

        tauri::async_runtime::block_on(async move {
            let cancelled_live = standalone_http_cancel("pre-cancel-1".to_string())
                .await
                .expect("cancel command result");
            assert!(!cancelled_live);

            let url = format!("http://{addr}/never-connected");
            let err = standalone_http_request(test_request(url, "pre-cancel-1"))
                .await
                .expect_err("pre-cancelled request must abort");
            assert!(err.starts_with(HTTP_ABORTED_PREFIX));
        });

        assert!(
            matches!(listener.accept(), Err(ref e) if e.kind() == ErrorKind::WouldBlock),
            "pre-cancelled request should not open a TCP connection"
        );
    }
}
