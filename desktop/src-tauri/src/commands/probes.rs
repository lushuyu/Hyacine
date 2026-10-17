//! Thin Rust wrappers around connectivity probes so the webview doesn't have
//! to hold the Claude key. For each probe we fetch the stored secret via
//! keyring, call the Python sidecar with the right params, and return.

use serde_json::json;
use tauri::{AppHandle, State};

use crate::commands::secrets::ProbeResult;
use crate::error::AppResult;
use crate::secrets;
use crate::sidecar::SidecarState;

#[tauri::command]
pub async fn rust_probe_claude(
    app: AppHandle,
    state: State<'_, SidecarState>,
) -> AppResult<ProbeResult> {
    // Route the "Claude" wizard card through `providers.test` so the check
    // actually exercises whatever provider the user picked (Claude Code OAuth,
    // Anthropic Console, DeepSeek, Kimi, Groq, Ollama, custom …) — not always
    // api.anthropic.com with the legacy `"claude"` keychain slug.
    let cur = state
        .rpc::<serde_json::Value>(&app, "providers.current", json!({}))
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
    // the legacy fallback via `?`. Only probe the active slot when non-empty.
    // The legacy `"claude"` slot holds a pre-multi-provider Claude token, so
    // it is only a fallback for the `claude` CLI: sending it to DeepSeek or
    // a custom relay would hand one provider's credential to another.
    let key = (if !slug.is_empty() { secrets::get(&slug)? } else { None })
        .or_else(|| {
            if api_format == "anthropic_cli" {
                secrets::get("claude").ok().flatten()
            } else {
                None
            }
        })
        .unwrap_or_default();

    let v = state
        .rpc::<serde_json::Value>(
            &app,
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

/// Test one provider with its own stored key: the wizard's "Test" button
/// when the key is already in the keychain and the webview never saw it.
///
/// The sidecar's `HYACINE_LLM_API_KEY` belongs to the *active* provider,
/// not necessarily the one under test, so it must not stand in for a
/// missing key. The slot is derived here from the provider under test (a
/// preset's `secret_slug`, or `custom` for a custom endpoint) and only that
/// slot is read, with no legacy-slot fallback.
///
/// A non-empty `api_key` (a key the user just typed) is used as is, so the
/// page can make every test through this one command.
#[tauri::command(rename_all = "camelCase")]
pub async fn rust_provider_test(
    app: AppHandle,
    state: State<'_, SidecarState>,
    provider_id: Option<String>,
    base_url: Option<String>,
    api_format: Option<String>,
    model: Option<String>,
    api_key: Option<String>,
) -> AppResult<serde_json::Value> {
    let provider_id = provider_id.unwrap_or_default().trim().to_string();
    let typed = api_key.unwrap_or_default().trim().to_string();
    let key = if !typed.is_empty() {
        typed
    } else {
        let slug = if provider_id.is_empty() {
            "custom".to_string()
        } else {
            let list = state
                .rpc::<serde_json::Value>(&app, "providers.list", json!({}))
                .await?;
            preset_secret_slug(&list, &provider_id)
        };
        secrets::get(&slug)?
            .map(|k| k.trim().to_string())
            .unwrap_or_default()
    };

    state
        .rpc::<serde_json::Value>(
            &app,
            "providers.test",
            json!({
                "provider_id": provider_id,
                "base_url": base_url.unwrap_or_default(),
                "api_format": api_format.unwrap_or_default(),
                "model": model.unwrap_or_default(),
                "api_key": key,
            }),
        )
        .await
}

/// Keychain slot for `provider_id`, as `providers.resolve` picks it: the
/// preset's own `secret_slug`, else the id itself.
fn preset_secret_slug(list: &serde_json::Value, provider_id: &str) -> String {
    list.get("providers")
        .and_then(|p| p.as_array())
        .into_iter()
        .flatten()
        .find(|p| p.get("id").and_then(|x| x.as_str()) == Some(provider_id))
        .and_then(|p| p.get("secret_slug"))
        .and_then(|x| x.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or(provider_id)
        .to_string()
}

#[tauri::command]
pub async fn rust_probe_graph(
    app: AppHandle,
    state: State<'_, SidecarState>,
) -> AppResult<ProbeResult> {
    // The sidecar reads the MSAL auth record on its own; we just ask it to probe.
    let me = state
        .rpc::<serde_json::Value>(&app, "graph.me", json!({}))
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
    app: AppHandle,
    recipient: String,
    state: State<'_, SidecarState>,
) -> AppResult<ProbeResult> {
    // graph.me carries a refresh — but for sendmail we also need the access
    // token. The sidecar's sendmail probe handles token acquisition itself via
    // the persisted MSAL record.
    let v = state
        .rpc::<serde_json::Value>(
            &app,
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

#[cfg(test)]
mod tests {
    use super::preset_secret_slug;
    use serde_json::json;

    #[test]
    fn stored_key_slot_comes_from_the_provider_under_test() {
        let list = json!({"providers": [
            {"id": "anthropic-console", "secret_slug": "anthropic-console"},
            {"id": "deepseek-anthropic", "secret_slug": "deepseek"},
            {"id": "groq", "secret_slug": ""},
        ]});
        assert_eq!(preset_secret_slug(&list, "deepseek-anthropic"), "deepseek");
        assert_eq!(preset_secret_slug(&list, "anthropic-console"), "anthropic-console");
        // Blank or unknown: the id itself, never another provider's slot.
        assert_eq!(preset_secret_slug(&list, "groq"), "groq");
        assert_eq!(preset_secret_slug(&list, "kimi-anthropic"), "kimi-anthropic");
        assert_eq!(preset_secret_slug(&json!({}), "openai"), "openai");
    }
}
