use serde::Serialize;

use crate::error::{AppError, AppResult};
use crate::secrets;

#[tauri::command]
pub async fn secrets_set(service: String, value: String) -> AppResult<()> {
    // Trim and reject obvious accidental copies of whole lines.
    let v = value.trim();
    if v.is_empty() {
        return Err(AppError::Other("empty secret".into()));
    }
    secrets::set(&service, v)
}

#[tauri::command]
pub async fn secrets_has(service: String) -> AppResult<bool> {
    secrets::has(&service)
}

#[tauri::command]
pub async fn secrets_remove(service: String) -> AppResult<()> {
    secrets::remove(&service)
}

#[derive(Serialize)]
pub struct ProbeResult {
    pub kind: String,
    pub status: String,
    pub latency_ms: u64,
    pub detail: String,
}

#[tauri::command]
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
    let model = model.unwrap_or_else(|| "claude-haiku-4-5".into());
    let start = std::time::Instant::now();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(crate::error::AppError::from)?;
    let body = serde_json::json!({
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    });
    let res = client
        .post("https://api.anthropic.com/v1/messages")
        .header("x-api-key", key)
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await;
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
