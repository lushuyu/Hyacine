//! Thin Rust wrappers around connectivity probes so the webview doesn't have
//! to hold the Claude key. For each probe we fetch the stored secret via
//! keyring, call the Python sidecar with the right params, and return.

use serde_json::json;
use tauri::State;

use crate::commands::secrets::ProbeResult;
use crate::error::AppResult;
use crate::secrets;
use crate::sidecar::SidecarState;

#[tauri::command]
pub async fn rust_probe_claude(state: State<'_, SidecarState>) -> AppResult<ProbeResult> {
    // Route the "Claude" wizard card through `providers.test` so the check
    // actually exercises whatever provider the user picked (Claude Code OAuth,
    // Anthropic Console, DeepSeek, Kimi, Groq, Ollama, custom …) — not always
    // api.anthropic.com with the legacy `"claude"` keychain slug.
    let cur = state
        .rpc::<serde_json::Value>("providers.current", json!({}))
        .await?;
    let current = cur.get("current").cloned().unwrap_or(serde_json::Value::Null);
    let slug = current
        .get("secret_slug")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let provider_id = current
        .get("id")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let api_format = current
        .get("api_format")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let base_url = current
        .get("base_url")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let model = current
        .get("default_model")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();

    // Pick the right keychain slot. `providers.current` may return an empty
    // `secret_slug` on fresh installs or unexpected shapes; `keyring::get`
    // with an empty slug errors on some backends, which would short-circuit
    // the legacy fallback via `?`. Only probe the active slot when non-empty
    // and always try the legacy `"claude"` slot as a safety net so
    // pre-multi-provider installs still pass without a reconfig.
    let key = (if !slug.is_empty() { secrets::get(&slug)? } else { None })
        .or_else(|| secrets::get("claude").ok().flatten())
        .unwrap_or_default();

    let v = state
        .rpc::<serde_json::Value>(
            "providers.test",
            json!({
                "provider_id": provider_id,
                "api_format": api_format,
                "base_url": base_url,
                "model": model,
                "api_key": key,
            }),
        )
        .await?;
    Ok(ProbeResult {
        kind: "claude".into(),
        status: v
            .get("status")
            .and_then(|x| x.as_str())
            .unwrap_or("fail")
            .into(),
        latency_ms: v.get("latency_ms").and_then(|x| x.as_u64()).unwrap_or(0),
        detail: v
            .get("detail")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .into(),
    })
}

#[tauri::command]
pub async fn rust_probe_graph(state: State<'_, SidecarState>) -> AppResult<ProbeResult> {
    // The sidecar reads the MSAL auth record on its own; we just ask it to probe.
    let me = state
        .rpc::<serde_json::Value>("graph.me", json!({}))
        .await?;
    let signed_in = me.get("signed_in").and_then(|x| x.as_bool()).unwrap_or(false);
    if !signed_in {
        return Ok(ProbeResult {
            kind: "graph".into(),
            status: "fail".into(),
            latency_ms: 0,
            detail: "not signed in".into(),
        });
    }
    let display = me
        .get("display_name")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let upn = me
        .get("user_principal_name")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    Ok(ProbeResult {
        kind: "graph".into(),
        status: "ok".into(),
        latency_ms: 0,
        detail: format!("{display} <{upn}>"),
    })
}

#[tauri::command]
pub async fn rust_probe_sendmail(
    recipient: String,
    state: State<'_, SidecarState>,
) -> AppResult<ProbeResult> {
    // graph.me carries a refresh — but for sendmail we also need the access
    // token. The sidecar's sendmail probe handles token acquisition itself via
    // the persisted MSAL record.
    let v = state
        .rpc::<serde_json::Value>(
            "connectivity.probe",
            json!({ "kind": "sendmail", "to": recipient }),
        )
        .await?;
    Ok(ProbeResult {
        kind: "sendmail".into(),
        status: v
            .get("status")
            .and_then(|x| x.as_str())
            .unwrap_or("fail")
            .into(),
        latency_ms: v.get("latency_ms").and_then(|x| x.as_u64()).unwrap_or(0),
        detail: v
            .get("detail")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .into(),
    })
}
