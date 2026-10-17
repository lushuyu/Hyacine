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
/// missing key. The slot is derived here from the provider under test and
/// read only when the request goes where that key was stored for:
///
/// * a preset id reads the preset's slot and is tested at the preset's own
///   endpoint; a `base_url` / `api_format` pointing elsewhere is refused;
/// * an empty id reads the shared `custom` slot, and only when the saved
///   provider is that same custom endpoint (format and base URL);
/// * any other id is refused, never mapped to a slot with the same name.
///
/// A refusal is a `fail` result asking for the key, and reads no keychain
/// slot. A non-empty `api_key` (a key the user just typed) is used as is,
/// so the page can make every test through this one command.
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
    let mut base_url = base_url.unwrap_or_default();
    let mut api_format = api_format.unwrap_or_default();
    let typed = api_key.unwrap_or_default().trim().to_string();
    let key = if !typed.is_empty() {
        typed
    } else {
        let slot = if provider_id.is_empty() {
            let cur = state
                .rpc::<serde_json::Value>(&app, "providers.current", json!({}))
                .await?;
            custom_slot(&cur, &base_url, &api_format)
        } else {
            let list = state
                .rpc::<serde_json::Value>(&app, "providers.list", json!({}))
                .await?;
            let slot = preset_slot(&list, &provider_id, &base_url, &api_format);
            // providers.test fills in the preset's own endpoint.
            base_url.clear();
            api_format.clear();
            slot
        };
        let slot = match slot {
            Ok(slot) => slot,
            Err(reason) => return Ok(stored_key_refused(reason)),
        };
        secrets::get(&slot)?
            .map(|k| k.trim().to_string())
            .unwrap_or_default()
    };

    state
        .rpc::<serde_json::Value>(
            &app,
            "providers.test",
            json!({
                "provider_id": provider_id,
                "base_url": base_url,
                "api_format": api_format,
                "model": model.unwrap_or_default(),
                "api_key": key,
            }),
        )
        .await
}

/// The `providers.test` result for a test that would need a stored key
/// somewhere it doesn't belong.
fn stored_key_refused(reason: &str) -> serde_json::Value {
    json!({
        "kind": "providers.test",
        "status": "fail",
        "latency_ms": 0,
        "detail": format!("enter the key to test this endpoint ({reason})"),
    })
}

fn str_field<'a>(v: &'a serde_json::Value, name: &str) -> &'a str {
    v.get(name).and_then(|x| x.as_str()).unwrap_or("")
}

/// Same endpoint, ignoring surrounding whitespace and trailing `/`.
fn same_base_url(a: &str, b: &str) -> bool {
    a.trim().trim_end_matches('/') == b.trim().trim_end_matches('/')
}

/// Keychain slot of preset `provider_id`, as `providers.resolve` picks it:
/// the preset's own `secret_slug`, else its id. An id that is not in
/// `providers.list` gets no slot, and neither does a request whose
/// `base_url` / `api_format` differs from the preset's (empty means the
/// preset's own).
fn preset_slot(
    list: &serde_json::Value,
    provider_id: &str,
    base_url: &str,
    api_format: &str,
) -> Result<String, &'static str> {
    let preset = list
        .get("providers")
        .and_then(|p| p.as_array())
        .into_iter()
        .flatten()
        .find(|p| str_field(p, "id") == provider_id)
        .ok_or("no stored key belongs to an unknown provider")?;
    let format_differs =
        !api_format.trim().is_empty() && api_format.trim() != str_field(preset, "api_format");
    let url_differs =
        !base_url.trim().is_empty() && !same_base_url(base_url, str_field(preset, "base_url"));
    if format_differs || url_differs {
        return Err("a preset's stored key is only sent to that preset's own endpoint");
    }
    let slug = str_field(preset, "secret_slug");
    Ok(if slug.is_empty() { provider_id } else { slug }.to_string())
}

/// The shared `custom` slot, when `providers.current` says the saved
/// provider is the custom endpoint under test: same format, same base URL.
/// Editing either, or picking Custom while a preset is active, needs the
/// key for the new endpoint.
fn custom_slot(
    current: &serde_json::Value,
    base_url: &str,
    api_format: &str,
) -> Result<String, &'static str> {
    let saved = current.get("current").unwrap_or(&serde_json::Value::Null);
    let matches = str_field(saved, "id") == "custom"
        && !api_format.trim().is_empty()
        && str_field(saved, "api_format") == api_format.trim()
        && !base_url.trim().is_empty()
        && same_base_url(str_field(saved, "base_url"), base_url);
    if matches {
        Ok("custom".to_string())
    } else {
        Err("the stored custom key is only used for the saved custom endpoint")
    }
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
    use super::{custom_slot, preset_slot, stored_key_refused};
    use serde_json::json;

    fn presets() -> serde_json::Value {
        json!({"providers": [
            {"id": "claude-code-oauth", "api_format": "anthropic_cli", "base_url": "",
             "secret_slug": "claude-code-oauth"},
            {"id": "anthropic-console", "api_format": "anthropic_http",
             "base_url": "https://api.anthropic.com", "secret_slug": "anthropic-console"},
            {"id": "deepseek-anthropic", "api_format": "anthropic_http",
             "base_url": "https://api.deepseek.com/anthropic", "secret_slug": "deepseek"},
            {"id": "groq", "api_format": "openai_chat",
             "base_url": "https://api.groq.com/openai/v1", "secret_slug": ""},
        ]})
    }

    #[test]
    fn stored_key_slot_comes_from_the_provider_under_test() {
        let list = presets();
        assert_eq!(preset_slot(&list, "deepseek-anthropic", "", "").unwrap(), "deepseek");
        assert_eq!(preset_slot(&list, "anthropic-console", "", "").unwrap(), "anthropic-console");
        assert_eq!(preset_slot(&list, "claude-code-oauth", "", "").unwrap(), "claude-code-oauth");
        // A blank secret_slug falls back to the preset's own id.
        assert_eq!(preset_slot(&list, "groq", "", "").unwrap(), "groq");
    }

    #[test]
    fn unknown_ids_get_no_slot() {
        // Never a keychain slot that merely shares the id's name.
        assert!(preset_slot(&presets(), "claude", "", "").is_err());
        assert!(preset_slot(&presets(), "custom", "", "").is_err());
        assert!(preset_slot(&presets(), "kimi-anthropic", "", "").is_err());
        assert!(preset_slot(&json!({}), "openai", "", "").is_err());
    }

    #[test]
    fn a_preset_key_only_goes_to_the_preset_endpoint() {
        let list = presets();
        // Restating the preset's own endpoint is fine.
        assert!(preset_slot(&list, "groq", "https://api.groq.com/openai/v1/", "openai_chat").is_ok());
        assert!(preset_slot(&list, "anthropic-console", "https://api.anthropic.com", "").is_ok());
        // Pointing it anywhere else is not.
        assert!(preset_slot(&list, "anthropic-console", "https://x.example", "").is_err());
        assert!(preset_slot(&list, "claude-code-oauth", "https://x.example", "openai_chat").is_err());
        assert!(preset_slot(&list, "claude-code-oauth", "", "openai_chat").is_err());
        assert!(preset_slot(&list, "deepseek-anthropic", "", "openai_chat").is_err());
    }

    #[test]
    fn the_custom_key_only_goes_to_the_saved_custom_endpoint() {
        let saved = json!({"current": {
            "id": "custom", "api_format": "openai_chat",
            "base_url": "https://relay-a.example/v1", "secret_slug": "custom",
        }});
        assert_eq!(
            custom_slot(&saved, "https://relay-a.example/v1", "openai_chat").unwrap(),
            "custom"
        );
        assert!(custom_slot(&saved, "https://relay-a.example/v1/", "openai_chat").is_ok());
        assert!(custom_slot(&saved, " https://relay-a.example/v1 ", "openai_chat").is_ok());

        // Another host or path, another format, or no endpoint at all.
        assert!(custom_slot(&saved, "https://relay-b.example/v1", "openai_chat").is_err());
        assert!(custom_slot(&saved, "https://relay-a.example", "openai_chat").is_err());
        assert!(custom_slot(&saved, "https://relay-a.example/v1", "anthropic_http").is_err());
        assert!(custom_slot(&saved, "", "openai_chat").is_err());
        assert!(custom_slot(&saved, "https://relay-a.example/v1", "").is_err());

        // A preset is active, though an old custom key may still be stored.
        let preset = json!({"current": {
            "id": "anthropic-console", "api_format": "anthropic_http",
            "base_url": "https://api.anthropic.com", "secret_slug": "anthropic-console",
        }});
        assert!(custom_slot(&preset, "https://api.anthropic.com", "anthropic_http").is_err());
        let none = json!({"current": null});
        assert!(custom_slot(&none, "https://relay-a.example/v1", "openai_chat").is_err());
        assert!(custom_slot(&json!({}), "https://relay-a.example/v1", "openai_chat").is_err());
    }

    #[test]
    fn a_refusal_is_a_failed_probe_asking_for_the_key() {
        let v = stored_key_refused("why");
        assert_eq!(v["kind"], "providers.test");
        assert_eq!(v["status"], "fail");
        assert_eq!(v["latency_ms"], 0);
        assert_eq!(v["detail"], "enter the key to test this endpoint (why)");
    }
}
