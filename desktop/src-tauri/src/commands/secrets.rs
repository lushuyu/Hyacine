//! Keychain-backed secret storage Tauri commands.
//!
//! Each stored value is addressed by a short slug (`claude`, `graph`, etc).
//! The fixed `keyring` service name is `hyacine`; the `slug` below is what
//! the frontend passes. We keep the API boundary to a strict minimum — get
//! is intentionally not exposed, since the webview should never need the
//! plaintext value. Connectivity tests go through `secrets_test_claude`,
//! which reads the value internally and returns only pass/fail + latency.

use serde::Serialize;

use crate::error::{AppError, AppResult};
use crate::secrets;

#[tauri::command]
pub async fn secrets_set(slug: String, value: String) -> AppResult<()> {
    // Trim so accidental whitespace doesn't silently break auth later.
    let v = value.trim();
    if v.is_empty() {
        return Err(AppError::Other("empty secret".into()));
    }
    secrets::set(&slug, v)
}

#[tauri::command]
pub async fn secrets_has(slug: String) -> AppResult<bool> {
    secrets::has(&slug)
}

#[tauri::command]
pub async fn secrets_remove(slug: String) -> AppResult<()> {
    secrets::remove(&slug)
}

#[derive(Serialize)]
pub struct ProbeResult {
    pub kind: String,
    pub status: String,
    pub latency_ms: u64,
    pub detail: String,
}

#[tauri::command(rename_all = "camelCase")]
pub async fn secrets_test_claude(api_key: String, model: Option<String>) -> AppResult<ProbeResult> {
    let key = api_key.trim();
    if key.is_empty() {
        return Ok(ProbeResult {
            kind: "claude".into(),
            status: "fail".into(),
            latency_ms: 0,
            detail: "empty key".into(),
        });
    }
    // "sonnet" matches Hyacine's existing CLI/config default. We avoid
    // hard-coding a full model identifier here since the messages API
    // resolves both short ("sonnet") and fully-qualified names.
    let model = model.unwrap_or_else(|| "sonnet".into());
    let start = std::time::Instant::now();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;
    let body = serde_json::json!({
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    });

    // Anthropic has two token families that *both* start with `sk-ant-`:
    //  * Console API keys (sk-ant-api03-…) → x-api-key header
    //  * Claude Code OAuth setup tokens (sk-ant-oat01-…) → Authorization: Bearer
    // Anything else (pure bearer token, short-lived JWT, etc) also goes via
    // Authorization: Bearer. Getting this wrong produces a 401 with
    // 'invalid x-api-key' even though the token is correct.
    let mut req = client
        .post("https://api.anthropic.com/v1/messages")
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json");
    req = if key.starts_with("sk-ant-api") {
        req.header("x-api-key", key)
    } else {
        req.header("authorization", format!("Bearer {key}"))
    };

    let res = req.json(&body).send().await;
    let latency = start.elapsed().as_millis() as u64;
    Ok(match res {
        Ok(r) if r.status().is_success() => ProbeResult {
            kind: "claude".into(),
            status: "ok".into(),
            latency_ms: latency,
            detail: format!("HTTP {}, model={}", r.status().as_u16(), model),
        },
        Ok(r) => {
            let code = r.status().as_u16();
            let text = r.text().await.unwrap_or_default();
            let snippet: String = text.chars().take(200).collect();
            ProbeResult {
                kind: "claude".into(),
                status: "fail".into(),
                latency_ms: latency,
                detail: format!("HTTP {code}: {snippet}"),
            }
        }
        Err(e) => ProbeResult {
            kind: "claude".into(),
            status: "fail".into(),
            latency_ms: latency,
            detail: e.to_string(),
        },
    })
}
