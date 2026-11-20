use std::{collections::HashMap, time::Duration};

use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StandaloneHttpRequest {
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

#[tauri::command]
pub async fn standalone_http_request(
    request: StandaloneHttpRequest,
) -> Result<StandaloneHttpResponse, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let parsed_method = reqwest::Method::from_bytes(request.method.trim().as_bytes())
            .map_err(|err| format!("Invalid HTTP method: {err}"))?;

        let timeout = Duration::from_millis(request.timeout_ms.unwrap_or(60_000).clamp(1_000, 180_000));
        let client = reqwest::blocking::Client::builder()
            .timeout(timeout)
            .build()
            .map_err(|err| format!("Failed to construct HTTP client: {err}"))?;

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

        let mut req_builder = client.request(parsed_method.clone(), &request.url).headers(header_map);
        if parsed_method != reqwest::Method::GET && parsed_method != reqwest::Method::HEAD {
            if let Some(b64) = request.body_base64 {
                let body_bytes = base64_decode(&b64)?;
                req_builder = req_builder.body(body_bytes);
            }
        }

        let response = req_builder
            .send()
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
            .map_err(|err| format!("Failed to read HTTP response body: {err}"))?;

        Ok(StandaloneHttpResponse {
            status,
            headers: resp_headers,
            body_base64: base64_encode(&body_bytes),
        })
    })
    .await
    .map_err(|err| format!("HTTP worker panicked: {err}"))?
}
