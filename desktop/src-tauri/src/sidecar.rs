//! Python sidecar lifecycle.
//!
//! Spawns `hyacine-ipc`, speaks newline-delimited JSON-RPC 2.0 over stdin/stdout,
//! and routes JSON-RPC notifications (events) to the webview via Tauri events.
//!
//! Every pending request is tracked by id in a shared map; the reader task
//! completes the oneshot when it sees the matching response. Notifications
//! (no `id`) are emitted to the frontend as `rpc:<method>` events.
//!
//! The reader buffers partial stdout chunks across `CommandEvent::Stdout`
//! arrivals, because the OS can split a line arbitrarily — a large JSON
//! response (e.g. rendered HTML) is routinely split into multiple pieces and
//! we must not treat them as independent frames.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{oneshot, Mutex};
use tokio::time::{timeout, Duration};

use crate::error::{AppError, AppResult};

type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Frame>>>>;

/// Result of routing a matched response frame to a waiting caller.
///
/// Keeping the success/error split in an enum here (instead of collapsing to
/// `Value`) means `SidecarState::rpc` can translate an RPC-level error into
/// an `AppError` and make `invoke()` reject — otherwise the webview would
/// receive an error body that looks like a successful result.
pub enum Frame {
    Ok(Value),
    Err { code: i64, message: String, data: Option<Value> },
}

pub struct SidecarState {
    inner: Arc<Mutex<Option<SidecarInner>>>,
    pending: Pending,
    next_id: AtomicU64,
}

struct SidecarInner {
    child: CommandChild,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(None)),
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: AtomicU64::new(1),
        }
    }

    pub async fn start(&self, app: &AppHandle) -> AppResult<()> {
        let mut guard = self.inner.lock().await;
        if guard.is_some() {
            return Ok(());
        }

        // Prefer the bundled sidecar binary; fall back to `python -m hyacine.ipc`
        // during development so you don't need to build the sidecar to iterate.
        let sidecar = app.shell().sidecar("hyacine-ipc");
        let (mut rx, child) = match sidecar {
            Ok(cmd) => cmd.spawn().map_err(|e| AppError::Sidecar(e.to_string()))?,
            Err(_) => {
                let python = which_python();
                app.shell()
                    .command(python)
                    .args(["-m", "hyacine.ipc"])
                    .spawn()
                    .map_err(|e| AppError::Sidecar(format!("fallback python: {e}")))?
            }
        };

        let app_for_reader = app.clone();
        let pending_for_reader = self.pending.clone();
        tauri::async_runtime::spawn(async move {
            // Buffer straddling partial lines across CommandEvent::Stdout chunks.
            let mut carry = String::new();
            while let Some(ev) = rx.recv().await {
                match ev {
                    CommandEvent::Stdout(bytes) => {
                        let s = String::from_utf8_lossy(&bytes);
                        carry.push_str(&s);
                        while let Some(idx) = carry.find('\n') {
                            let line = carry[..idx].trim().to_string();
                            carry.drain(..=idx);
                            if !line.is_empty() {
                                handle_frame(&app_for_reader, &pending_for_reader, &line).await;
                            }
                        }
                    }
                    CommandEvent::Stderr(bytes) => {
                        // The sidecar emits structured JSON logs to stderr, but
                        // a Python traceback could still carry an API key in a
                        // repr()ed request. Redact before tracing — the same
                        // guarantee the webview-side logger already enforces.
                        let s = String::from_utf8_lossy(&bytes);
                        let cleaned = crate::redact::scrub(s.trim());
                        tracing::info!(target = "sidecar", "{}", cleaned);
                    }
                    CommandEvent::Error(e) => {
                        tracing::error!("sidecar error: {e}");
                    }
                    CommandEvent::Terminated(payload) => {
                        tracing::warn!("sidecar terminated: {:?}", payload);
                        // Drain leftover buffer — last frame may not be newline-terminated.
                        let tail = carry.trim();
                        if !tail.is_empty() {
                            handle_frame(&app_for_reader, &pending_for_reader, tail).await;
                        }
                        break;
                    }
                    _ => {}
                }
            }
        });

        *guard = Some(SidecarInner { child });
        Ok(())
    }

    pub async fn stop(&self) -> AppResult<()> {
        let mut guard = self.inner.lock().await;
        if let Some(inner) = guard.take() {
            let _ = inner.child.kill();
        }
        Ok(())
    }

    pub async fn rpc<T: serde::de::DeserializeOwned>(
        &self,
        method: &str,
        params: Value,
    ) -> AppResult<T> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id, tx);

        let frame = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });
        let line = serde_json::to_string(&frame)? + "\n";

        {
            let mut guard = self.inner.lock().await;
            let inner = match guard.as_mut() {
                Some(v) => v,
                None => {
                    // No child — leak would never happen since we haven't sent
                    // anything, but be defensive and clean the pending entry.
                    self.pending.lock().await.remove(&id);
                    return Err(AppError::Sidecar("not started".into()));
                }
            };
            if let Err(e) = inner.child.write(line.as_bytes()) {
                self.pending.lock().await.remove(&id);
                return Err(AppError::Sidecar(format!("write: {e}")));
            }
        }

        let outcome = match timeout(Duration::from_secs(60), rx).await {
            Ok(Ok(frame)) => frame,
            Ok(Err(_)) => {
                // Sender dropped without sending — likely the reader task died.
                self.pending.lock().await.remove(&id);
                return Err(AppError::Sidecar("pending dropped".into()));
            }
            Err(_) => {
                // Timeout: cleanup pending so the map doesn't grow unbounded.
                self.pending.lock().await.remove(&id);
                return Err(AppError::Sidecar(format!("rpc timeout: {method}")));
            }
        };

        match outcome {
            Frame::Ok(v) => serde_json::from_value(v).map_err(Into::into),
            Frame::Err { code, message, data } => {
                let detail = data
                    .map(|d| format!("{message} ({d})"))
                    .unwrap_or(message);
                Err(AppError::Sidecar(format!("rpc {code}: {detail}")))
            }
        }
    }
}

async fn handle_frame(app: &AppHandle, pending: &Pending, line: &str) {
    let Ok(v) = serde_json::from_str::<Value>(line) else {
        tracing::warn!("non-json sidecar line: {line}");
        return;
    };

    // Response to a request.
    if let Some(id) = v.get("id").and_then(|x| x.as_u64()) {
        let mut map = pending.lock().await;
        if let Some(tx) = map.remove(&id) {
            let frame = if let Some(result) = v.get("result") {
                Frame::Ok(result.clone())
            } else if let Some(err) = v.get("error") {
                Frame::Err {
                    code: err.get("code").and_then(|c| c.as_i64()).unwrap_or(-32603),
                    message: err
                        .get("message")
                        .and_then(|m| m.as_str())
                        .unwrap_or("rpc error")
                        .to_string(),
                    data: err.get("data").cloned(),
                }
            } else {
                Frame::Ok(Value::Null)
            };
            let _ = tx.send(frame);
        }
        return;
    }

    // Notification/event.
    if let Some(method) = v.get("method").and_then(|m| m.as_str()) {
        let evt_name = format!("rpc:{method}");
        let payload = v.get("params").cloned().unwrap_or(Value::Null);
        let _ = app.emit(&evt_name, payload);
    }
}

fn which_python() -> &'static str {
    if cfg!(windows) {
        "python"
    } else {
        "python3"
    }
}

#[allow(dead_code)]
pub fn state<'a>(app: &'a AppHandle) -> tauri::State<'a, SidecarState> {
    app.state::<SidecarState>()
}
