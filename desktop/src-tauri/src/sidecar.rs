//! Python sidecar lifecycle.
//!
//! Spawns `hyacine-ipc`, speaks newline-delimited JSON-RPC 2.0 over stdin/stdout,
//! and routes JSON-RPC notifications (events) to the webview via Tauri events.
//!
//! Every pending request is tracked by id in a shared map; the reader task
//! completes the oneshot when it sees the matching response. Notifications
//! (no `id`) are emitted to the frontend as `rpc:<method>` events.

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

type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Value>>>>;

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
            while let Some(ev) = rx.recv().await {
                match ev {
                    CommandEvent::Stdout(line) => {
                        let s = String::from_utf8_lossy(&line).to_string();
                        for chunk in s.split('\n') {
                            let chunk = chunk.trim();
                            if chunk.is_empty() {
                                continue;
                            }
                            handle_frame(&app_for_reader, &pending_for_reader, chunk).await;
                        }
                    }
                    CommandEvent::Stderr(line) => {
                        let s = String::from_utf8_lossy(&line).to_string();
                        tracing::info!(target = "sidecar", "{}", s.trim());
                    }
                    CommandEvent::Error(e) => {
                        tracing::error!("sidecar error: {e}");
                    }
                    CommandEvent::Terminated(payload) => {
                        tracing::warn!("sidecar terminated: {:?}", payload);
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
            let guard = self.inner.lock().await;
            let inner = guard
                .as_ref()
                .ok_or_else(|| AppError::Sidecar("not started".into()))?;
            inner
                .child
                .write(line.as_bytes())
                .map_err(|e| AppError::Sidecar(format!("write: {e}")))?;
        }

        let result = timeout(Duration::from_secs(60), rx)
            .await
            .map_err(|_| AppError::Sidecar(format!("rpc timeout: {method}")))?
            .map_err(|_| AppError::Sidecar("pending dropped".into()))?;

        serde_json::from_value(result).map_err(Into::into)
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
            if let Some(result) = v.get("result") {
                let _ = tx.send(result.clone());
            } else if let Some(err) = v.get("error") {
                let _ = tx.send(json!({ "__error": err }));
            } else {
                let _ = tx.send(Value::Null);
            }
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

pub fn state<'a>(app: &'a AppHandle) -> tauri::State<'a, SidecarState> {
    app.state::<SidecarState>()
}
