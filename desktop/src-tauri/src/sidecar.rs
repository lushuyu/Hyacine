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
//!
//! The child is started lazily by the first call that needs it (the root
//! page's first RPC can reach us before the layout's `sidecar_start`), and
//! respawned by the next call after it exits. Each child gets a generation
//! number so a dying child only fails the calls that were sent to it.
//!
//! Credentials reach the Python backends through env vars set at spawn, so
//! a keychain or provider change marks them stale; the next call compares
//! the fresh set against the running child's and respawns it when they
//! differ and nothing is in flight.

use std::collections::hash_map::RandomState;
use std::collections::HashMap;
use std::hash::BuildHasher;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{oneshot, Mutex, MutexGuard};
use tokio::time::{timeout_at, Duration, Instant};

use crate::error::{AppError, AppResult};

type Pending = Arc<Mutex<HashMap<u64, PendingCall>>>;

struct PendingCall {
    tx: oneshot::Sender<Frame>,
    /// Child the request was written to.
    generation: u64,
    /// When the caller stops waiting.
    deadline: Instant,
}

/// Default budget for a call. Probes and config reads finish in seconds.
const RPC_TIMEOUT: Duration = Duration::from_secs(60);
/// `connectivity.probe_all` runs the DNS, Claude, Graph and sendMail probes
/// back to back, each with its own network timeout.
const PROBE_ALL_TIMEOUT: Duration = Duration::from_secs(3 * 60);
/// Pipeline time outside the LLM call: paged Graph fetch with retry/backoff,
/// rendering and sendMail.
const PIPELINE_MARGIN: Duration = Duration::from_secs(15 * 60);
/// Mirrors `YamlConfig.llm_timeout_seconds` in src/hyacine/config.py.
const DEFAULT_LLM_TIMEOUT_SECS: u64 = 300;
/// Upper bound on a configured LLM timeout, so a typo can't overflow the
/// deadline arithmetic.
const MAX_LLM_TIMEOUT_SECS: u64 = 24 * 60 * 60;

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
    next_generation: AtomicU64,
    /// Set when a keychain secret or config.yaml may have changed which
    /// credential the sidecar should hold.
    credentials_stale: AtomicBool,
    /// Keyed per process; only used to compare credential sets without
    /// keeping the secrets themselves around.
    hasher: RandomState,
}

struct SidecarInner {
    child: CommandChild,
    generation: u64,
    data_root: Option<PathBuf>,
    /// Fingerprint of the credential env vars this child was spawned with.
    credentials: u64,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(None)),
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: AtomicU64::new(1),
            next_generation: AtomicU64::new(1),
            credentials_stale: AtomicBool::new(false),
            hasher: RandomState::new(),
        }
    }

    /// Start the sidecar if it isn't running. Idempotent; `rpc` does the
    /// same on every call, so this only exists to surface a spawn failure
    /// early (the layout shows it as a banner).
    pub async fn start(&self, app: &AppHandle) -> AppResult<()> {
        let mut guard = self.inner.lock().await;
        self.ensure_running(app, &mut guard).await
    }

    /// Ask the next call to re-read the credentials the sidecar should hold.
    pub fn mark_credentials_stale(&self) {
        self.credentials_stale.store(true, Ordering::SeqCst);
    }

    /// Make sure a child with current credentials is in `guard`. Caller
    /// holds the `inner` lock, so concurrent callers serialise behind one
    /// spawn.
    async fn ensure_running(
        &self,
        app: &AppHandle,
        guard: &mut MutexGuard<'_, Option<SidecarInner>>,
    ) -> AppResult<()> {
        if let Some((generation, data_root, credentials)) = guard
            .as_ref()
            .map(|i| (i.generation, i.data_root.clone(), i.credentials))
        {
            // Clear the flag before reading the keychain: a secret saved
            // while we read sets it again and is picked up next call.
            if !self.credentials_stale.swap(false, Ordering::SeqCst) {
                return Ok(());
            }
            let fresh = credential_env(data_root.as_deref());
            if self.hasher.hash_one(&fresh) == credentials {
                return Ok(());
            }
            let busy = self
                .pending
                .lock()
                .await
                .values()
                .any(|p| p.generation == generation);
            if busy {
                // Respawning now would kill a call that is still running (a
                // `pipeline.run` may be mid-sendMail). Keep the old child
                // and check again on the next call.
                self.credentials_stale.store(true, Ordering::SeqCst);
                return Ok(());
            }
            tracing::info!("sidecar: credentials changed; respawning so the backend sees them");
            if let Some(old) = guard.take() {
                let _ = old.child.kill();
            }
        }

        self.credentials_stale.store(false, Ordering::SeqCst);
        let inner = self.spawn(app)?;
        **guard = Some(inner);
        Ok(())
    }

    fn spawn(&self, app: &AppHandle) -> AppResult<SidecarInner> {
        // One per-user data root for config.yaml, the watermark DB and the
        // Graph auth record, shared by the sidecar (via HYACINE_REPO_ROOT)
        // and our own config.yaml reads below.
        let data_root = resolve_data_root(app);

        // Build the child environment. The backend pipeline (hyacine.llm
        // .claude_code.build_env) requires CLAUDE_CODE_OAUTH_TOKEN and
        // explicitly deletes ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN; mirror
        // that contract here so "Run now" works the moment the wizard
        // finishes, without the user having to export anything.
        let credentials = credential_env(data_root.as_deref());
        let fingerprint = self.hasher.hash_one(&credentials);
        let env = build_sidecar_env(data_root.as_deref(), &credentials);

        // Prefer the bundled sidecar binary; fall back to `python -m hyacine.ipc`
        // during development or on installers that ship without the bundled
        // sidecar binary. The fallback itself requires Python on PATH — when
        // that's also missing, the combined error message at the bottom names
        // both failed attempts and points at `pip install hyacine`.
        //
        // Tauri 2's `app.shell().sidecar(name)` ALWAYS returns `Ok(cmd)` — it
        // constructs a Command pointing at `{resource_dir}/hyacine-ipc` without
        // touching the disk. The actual existence check happens at `.spawn()`.
        // The previous match shape (Ok => spawn()?, Err => fallback) therefore
        // never reached the Python fallback on installer builds: the bundled
        // path returned Ok(cmd), spawn() failed with OS error 2 ("file not
        // found"), and the `?` bubbled up the bundled error — leaving users on
        // a clean install staring at "bundled sidecar failed to spawn" with no
        // Python attempt ever made.
        //
        // Fix (issue #10): on spawn failure cascade to the Python fallback.
        // When both fail, surface a combined message that names both attempts.
        let python = which_python();
        let (mut rx, child) = match app.shell().sidecar("hyacine-ipc") {
            Ok(cmd) => match cmd.envs(env.clone()).spawn() {
                Ok(pair) => {
                    tracing::info!("sidecar: spawned bundled `hyacine-ipc`");
                    pair
                }
                Err(bundled_err) => {
                    tracing::info!(
                        "bundled `hyacine-ipc` spawn failed ({bundled_err}); \
                         falling back to `{python} -m hyacine.ipc`"
                    );
                    app.shell()
                        .command(python)
                        .args(["-m", "hyacine.ipc"])
                        .envs(env)
                        .spawn()
                        .map_err(|py_err| {
                            AppError::Sidecar(format!(
                                "Sidecar unavailable. Bundled `hyacine-ipc`: {bundled_err}. \
                                 Python fallback `{python} -m hyacine.ipc`: {py_err}. \
                                 Install Python 3.11+ with `pip install hyacine` (or clone \
                                 the repo and `uv sync`) to enable connectivity testing and \
                                 pipeline runs. The wizard picker still works offline."
                            ))
                        })?
                }
            },
            Err(sidecar_err) => app
                .shell()
                .command(python)
                .args(["-m", "hyacine.ipc"])
                .envs(env)
                .spawn()
                .map_err(|py_err| {
                    AppError::Sidecar(format!(
                        "Sidecar unavailable. Bundled sidecar plugin: {sidecar_err}. \
                         Python fallback `{python} -m hyacine.ipc`: {py_err}. \
                         Install Python 3.11+ with `pip install hyacine` (or clone the \
                         repo and `uv sync`)."
                    ))
                })?,
        };

        let generation = self.next_generation.fetch_add(1, Ordering::Relaxed);
        let app_for_reader = app.clone();
        let inner_for_reader = self.inner.clone();
        let pending_for_reader = self.pending.clone();
        tauri::async_runtime::spawn(async move {
            // Buffer straddling partial lines across CommandEvent::Stdout chunks.
            let mut carry = String::new();
            let mut reason = String::from("sidecar terminated");
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
                        if let Some(code) = payload.code {
                            reason = format!("sidecar terminated (exit code {code})");
                        } else if let Some(signal) = payload.signal {
                            reason = format!("sidecar terminated (signal {signal})");
                        }
                        break;
                    }
                    _ => {}
                }
            }
            // The child is gone. Forget it so the next call respawns, unless
            // it was already replaced. Release `inner` before taking
            // `pending`: `rpc` and `stop` lock them in that order.
            {
                let mut guard = inner_for_reader.lock().await;
                if guard.as_ref().is_some_and(|i| i.generation == generation) {
                    *guard = None;
                }
            }
            // Fail this child's in-flight RPCs fast instead of making them
            // wait out their timeout. We send Frame::Err so the webview gets
            // a clean AppError rather than a 'pending dropped' placeholder.
            fail_pending(&pending_for_reader, Some(generation), &reason).await;
        });

        Ok(SidecarInner {
            child,
            generation,
            data_root,
            credentials: fingerprint,
        })
    }

    pub async fn stop(&self) -> AppResult<()> {
        let mut guard = self.inner.lock().await;
        if let Some(inner) = guard.take() {
            let _ = inner.child.kill();
        }
        // Same drain as the terminated path — stop() is a deliberate kill, so
        // pending callers shouldn't block on the RPC timeout either.
        fail_pending(&self.pending, None, "sidecar stopped").await;
        Ok(())
    }

    pub async fn rpc<T: serde::de::DeserializeOwned>(
        &self,
        app: &AppHandle,
        method: &str,
        params: Value,
    ) -> AppResult<T> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let frame = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });
        let line = serde_json::to_string(&frame)? + "\n";
        let (tx, rx) = oneshot::channel();

        let deadline = {
            let mut guard = self.inner.lock().await;
            let mut tx = Some(tx);
            let mut respawned = false;
            loop {
                self.ensure_running(app, &mut guard).await?;
                let Some(inner) = guard.as_mut() else {
                    return Err(AppError::Sidecar("not started".into()));
                };
                let generation = inner.generation;
                let budget = rpc_timeout(method, inner.data_root.as_deref());
                // Register before writing so the response can't beat us to
                // the map. We still hold `inner`, so the reader of a dying
                // child can't drain this entry before we know the write
                // outcome.
                let deadline = {
                    let mut map = self.pending.lock().await;
                    let deadline = queued_deadline(
                        Instant::now(),
                        budget,
                        map.values()
                            .filter(|p| p.generation == generation)
                            .map(|p| p.deadline),
                    );
                    let Some(sender) = tx.take() else {
                        return Err(AppError::Sidecar("pending dropped".into()));
                    };
                    map.insert(id, PendingCall { tx: sender, generation, deadline });
                    deadline
                };
                match inner.child.write(line.as_bytes()) {
                    Ok(()) => break deadline,
                    Err(e) => {
                        tx = self.pending.lock().await.remove(&id).map(|p| p.tx);
                        if respawned {
                            return Err(AppError::Sidecar(format!("write: {e}")));
                        }
                        // The child's stdin is closed: it exited and its
                        // reader hasn't cleared it yet. Nothing was
                        // delivered, so replace it and send once more.
                        tracing::warn!("sidecar: write failed ({e}); respawning");
                        if let Some(dead) = guard.take() {
                            let _ = dead.child.kill();
                        }
                        respawned = true;
                    }
                }
            }
        };

        let outcome = timeout_at(deadline, rx).await;
        if affects_credentials(method) {
            // config.write may have switched llm_provider / llm_api_format,
            // which changes which keychain slot the sidecar should hold.
            self.mark_credentials_stale();
        }
        let outcome = match outcome {
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

/// Fail in-flight calls with `message`: those sent to `generation`, or all
/// of them when `None`.
async fn fail_pending(pending: &Pending, generation: Option<u64>, message: &str) {
    let mut map = pending.lock().await;
    let ids: Vec<u64> = map
        .iter()
        .filter(|(_, p)| generation.map_or(true, |g| p.generation == g))
        .map(|(id, _)| *id)
        .collect();
    for id in ids {
        if let Some(p) = map.remove(&id) {
            let _ = p.tx.send(Frame::Err {
                code: -32002,
                message: message.into(),
                data: None,
            });
        }
    }
}

/// How long a caller waits for `method` once the sidecar starts on it.
///
/// The pipeline blocks the single-threaded sidecar for the Graph fetch, the
/// LLM call (up to `llm_timeout_seconds`) and sendMail. Cutting it off at
/// the default would report a failure while the run carries on and still
/// mails the digest.
fn rpc_timeout(method: &str, data_root: Option<&Path>) -> Duration {
    match method {
        "pipeline.run" | "pipeline.dry_run" => pipeline_timeout(
            read_config_hints(data_root).and_then(|h| h.llm_timeout_seconds),
        ),
        "connectivity.probe_all" => PROBE_ALL_TIMEOUT,
        _ => RPC_TIMEOUT,
    }
}

fn pipeline_timeout(llm_timeout_secs: Option<u64>) -> Duration {
    let llm = llm_timeout_secs
        .filter(|s| *s > 0)
        .unwrap_or(DEFAULT_LLM_TIMEOUT_SECS)
        .min(MAX_LLM_TIMEOUT_SECS);
    Duration::from_secs(llm) + PIPELINE_MARGIN
}

/// The sidecar answers requests one at a time, in order, so a call queued
/// behind a still-pending one can't finish before that one does. Start its
/// clock at the latest earlier deadline instead of now, so a quick
/// `config.read` sent during a long run doesn't time out while it waits.
fn queued_deadline(
    now: Instant,
    budget: Duration,
    earlier: impl Iterator<Item = Instant>,
) -> Instant {
    earlier.fold(now, Instant::max) + budget
}

/// Methods after which the credential env may need refreshing.
fn affects_credentials(method: &str) -> bool {
    method == "config.write"
}

async fn handle_frame(app: &AppHandle, pending: &Pending, line: &str) {
    let Ok(v) = serde_json::from_str::<Value>(line) else {
        // If Python ever prints outside the RPC channel (a stray print in a
        // traceback, etc.) it could theoretically carry a token. Scrub
        // before tracing, same as the stderr path.
        tracing::warn!("non-json sidecar line: {}", crate::redact::scrub(line));
        return;
    };

    // Response to a request.
    if let Some(id) = v.get("id").and_then(|x| x.as_u64()) {
        let mut map = pending.lock().await;
        if let Some(call) = map.remove(&id) {
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
            let _ = call.tx.send(frame);
        }
        return;
    }

    // Notification/event.
    //
    // Tauri 2's `listen` command rejects event names with `.` (allowed set:
    // alphanumeric, `-`, `/`, `:`, `_`). JSON-RPC methods are `area.verb`,
    // so we translate `.` → `/` on the way out: `graph.device_flow` becomes
    // `rpc:graph/device_flow`. Frontend subscriptions use the slash form.
    if let Some(method) = v.get("method").and_then(|m| m.as_str()) {
        let evt_name = format!("rpc:{}", method.replace('.', "/"));
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

/// Where the sidecar keeps config.yaml, rules, the prompt, the watermark DB
/// and the Graph auth record.
///
/// An explicit `HYACINE_REPO_ROOT` wins (a developer pointing the app at a
/// repo checkout). Otherwise the per-user app data dir. Without this the
/// frozen sidecar anchors everything next to its PyInstaller extraction
/// dir, i.e. the OS temp dir, which is wiped on reboot and shared between
/// users on Linux. desktop/sidecar/entry.py derives the same directory when
/// the binary runs without us.
fn resolve_data_root(app: &AppHandle) -> Option<PathBuf> {
    let home = app.path().home_dir().ok();
    if let Some(root) = repo_root_override(std::env::var("HYACINE_REPO_ROOT").ok(), home) {
        return Some(root);
    }
    // app_local_data_dir, not app_data_dir: on Windows the latter is the
    // roaming profile, which is no place for a SQLite DB and an auth
    // record. Elsewhere they're the same directory.
    match app.path().app_local_data_dir() {
        Ok(dir) => {
            if let Err(e) = std::fs::create_dir_all(&dir) {
                tracing::warn!("sidecar: could not create data dir {}: {e}", dir.display());
            }
            Some(dir)
        }
        Err(e) => {
            tracing::warn!("sidecar: no app data dir ({e}); the sidecar picks its own");
            None
        }
    }
}

/// `HYACINE_REPO_ROOT` as Python's config.py reads it (trimmed, `~`
/// expanded), or `None` when unset or blank.
fn repo_root_override(raw: Option<String>, home: Option<PathBuf>) -> Option<PathBuf> {
    let raw = raw?;
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let (Some(rest), Some(home)) = (trimmed.strip_prefix('~'), home) {
        if rest.is_empty() {
            return Some(home);
        }
        if let Some(rel) = rest.strip_prefix('/').or_else(|| rest.strip_prefix('\\')) {
            return Some(home.join(rel));
        }
    }
    Some(PathBuf::from(trimmed))
}

/// Legacy priority list — only consulted when the active provider's slug
/// has no stored secret. Preserves the pre-provider-registry behaviour so
/// upgrades from older installs don't lose the user's token.
const LEGACY_SLUG_CANDIDATES: &[&str] = &["claude-code-oauth", "claude"];

/// Build the env var map the sidecar process inherits on spawn.
fn build_sidecar_env(
    data_root: Option<&Path>,
    credentials: &[(&'static str, String)],
) -> HashMap<String, String> {
    let mut env: HashMap<String, String> = std::env::vars().collect();
    apply_sidecar_env(&mut env, data_root, credentials);
    env
}

/// Layer our settings over the inherited environment.
///
/// Anthropic's scrubbing contract is honoured throughout:
/// ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` are removed so stale
/// shell env can't silently override whatever we just set.
fn apply_sidecar_env(
    env: &mut HashMap<String, String>,
    data_root: Option<&Path>,
    credentials: &[(&'static str, String)],
) {
    if let Some(root) = data_root {
        let explicit = env
            .get("HYACINE_REPO_ROOT")
            .is_some_and(|v| !v.trim().is_empty());
        if !explicit {
            env.insert("HYACINE_REPO_ROOT".into(), root.display().to_string());
        }
    }
    // serde_json writes raw UTF-8, but Python < 3.15 on Windows decodes a
    // piped stdin with the ANSI code page, which garbles or crashes on a
    // zh-CN prompt. This covers the `python -m hyacine.ipc` fallback; the
    // frozen binary ignores PYTHON* env vars, so hyacine-ipc.spec turns on
    // UTF-8 mode there.
    env.insert("PYTHONUTF8".into(), "1".into());
    env.insert("PYTHONIOENCODING".into(), "utf-8".into());
    for (key, value) in credentials {
        env.insert((*key).to_string(), value.clone());
    }
    env.remove("ANTHROPIC_API_KEY");
    env.remove("ANTHROPIC_AUTH_TOKEN");
}

/// The credential env vars the sidecar should hold right now.
///
/// Two env vars carry credentials to the Python backends:
///   * ``CLAUDE_CODE_OAUTH_TOKEN`` — ``anthropic_cli`` backend (authentic
///     ates the local ``claude`` binary through OAuth).
///   * ``HYACINE_LLM_API_KEY`` — generic slot read by ``anthropic_http`` +
///     ``openai_chat`` backends.
///
/// We first ask the config which provider is active and fetch *that*
/// slug's secret. Only when it's empty do we scan the legacy list, so a
/// user with multiple providers stored can still switch between them
/// without the sidecar exporting the wrong one.
fn credential_env(data_root: Option<&Path>) -> Vec<(&'static str, String)> {
    let active = read_config_hints(data_root).and_then(|h| h.active_provider());
    credential_env_from(active, |slug| crate::secrets::get(slug).ok().flatten())
}

fn credential_env_from(
    active: Option<(String, bool)>,
    lookup: impl Fn(&str) -> Option<String>,
) -> Vec<(&'static str, String)> {
    // Try the active provider's slug first, then the legacy fallback list.
    let mut candidates: Vec<(String, bool /* is_cli */)> = Vec::new();
    if let Some((slug, is_cli)) = active {
        candidates.push((slug, is_cli));
    }
    for legacy in LEGACY_SLUG_CANDIDATES {
        candidates.push(((*legacy).to_string(), true)); // legacy slugs always CLI-auth
    }

    for (slug, is_cli) in candidates {
        let Some(token) = lookup(&slug) else { continue };
        let trimmed = token.trim().to_string();
        if trimmed.is_empty() {
            continue;
        }
        tracing::info!(slug = slug.as_str(), cli = is_cli, "loaded sidecar credential from keychain");
        return if is_cli {
            vec![
                ("CLAUDE_CODE_OAUTH_TOKEN", trimmed.clone()),
                ("HYACINE_CLAUDE_CODE_OAUTH_TOKEN", trimmed),
            ]
        } else {
            vec![("HYACINE_LLM_API_KEY", trimmed)]
        };
    }
    Vec::new()
}

/// The few config.yaml keys the Rust side needs.
#[derive(Debug, Default, PartialEq)]
struct ConfigHints {
    llm_provider: Option<String>,
    llm_api_format: Option<String>,
    llm_timeout_seconds: Option<u64>,
}

impl ConfigHints {
    /// ``Some((slug, is_cli))`` when a provider is resolvable, so the
    /// spawner knows which keychain slug to load.
    fn active_provider(&self) -> Option<(String, bool)> {
        let id = self.llm_provider.as_deref().unwrap_or_default();
        let fmt = self.llm_api_format.as_deref().unwrap_or_default();
        if !id.is_empty() {
            let is_cli = matches!(id, "claude-code-oauth");
            return Some((id.to_string(), is_cli));
        }
        if !fmt.is_empty() {
            let is_cli = fmt == "anthropic_cli";
            return Some(("custom".to_string(), is_cli));
        }
        None
    }
}

/// Read `<data_root>/config/config.yaml`, the file the sidecar writes.
fn read_config_hints(data_root: Option<&Path>) -> Option<ConfigHints> {
    let path = data_root?.join("config").join("config.yaml");
    let body = std::fs::read_to_string(path).ok()?;
    Some(parse_config_hints(&body))
}

/// Tiny line-based parser — we only need a few top-level scalar keys.
/// Avoids pulling serde_yaml into the binary just for this.
fn parse_config_hints(body: &str) -> ConfigHints {
    let mut hints = ConfigHints::default();
    for line in body.lines() {
        // Top-level keys only: nested mappings and block scalars are indented.
        if line.starts_with(char::is_whitespace) {
            continue;
        }
        if let Some(val) = line.strip_prefix("llm_provider:") {
            hints.llm_provider = Some(strip_yaml_scalar(val));
        } else if let Some(val) = line.strip_prefix("llm_api_format:") {
            hints.llm_api_format = Some(strip_yaml_scalar(val));
        } else if let Some(val) = line.strip_prefix("llm_timeout_seconds:") {
            hints.llm_timeout_seconds = strip_yaml_scalar(val).parse().ok();
        }
    }
    hints
}

fn strip_yaml_scalar(raw: &str) -> String {
    let s = raw.trim();
    for quote in ['"', '\''] {
        if let Some(rest) = s.strip_prefix(quote) {
            return rest.split(quote).next().unwrap_or_default().to_string();
        }
    }
    // Unquoted: a ` #` starts a comment.
    s.split(" #").next().unwrap_or_default().trim().to_string()
}

#[allow(dead_code)]
pub fn state<'a>(app: &'a AppHandle) -> tauri::State<'a, SidecarState> {
    app.state::<SidecarState>()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pipeline_calls_get_the_llm_timeout_plus_margin() {
        assert_eq!(pipeline_timeout(Some(600)), Duration::from_secs(600) + PIPELINE_MARGIN);
        assert_eq!(
            pipeline_timeout(None),
            Duration::from_secs(DEFAULT_LLM_TIMEOUT_SECS) + PIPELINE_MARGIN
        );
        assert_eq!(
            pipeline_timeout(Some(0)),
            Duration::from_secs(DEFAULT_LLM_TIMEOUT_SECS) + PIPELINE_MARGIN
        );
        assert_eq!(
            pipeline_timeout(Some(u64::MAX)),
            Duration::from_secs(MAX_LLM_TIMEOUT_SECS) + PIPELINE_MARGIN
        );
    }

    #[test]
    fn rpc_timeout_reads_llm_timeout_from_the_data_root() {
        let root = std::env::temp_dir().join(format!("hyacine-rpc-timeout-{}", std::process::id()));
        std::fs::create_dir_all(root.join("config")).unwrap();
        std::fs::write(
            root.join("config").join("config.yaml"),
            "llm_model: claude-opus-5-5\nllm_timeout_seconds: 900\n",
        )
        .unwrap();

        let expected = Duration::from_secs(900) + PIPELINE_MARGIN;
        assert_eq!(rpc_timeout("pipeline.run", Some(&root)), expected);
        assert_eq!(rpc_timeout("pipeline.dry_run", Some(&root)), expected);
        assert_eq!(rpc_timeout("config.read", Some(&root)), RPC_TIMEOUT);
        assert_eq!(rpc_timeout("providers.test", Some(&root)), RPC_TIMEOUT);
        assert_eq!(rpc_timeout("connectivity.probe_all", Some(&root)), PROBE_ALL_TIMEOUT);
        // No config yet (first run): fall back to the default LLM timeout.
        assert_eq!(rpc_timeout("pipeline.run", None), pipeline_timeout(None));

        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn queued_calls_start_their_clock_after_earlier_pending_calls() {
        let now = Instant::now();
        let budget = Duration::from_secs(60);
        assert_eq!(queued_deadline(now, budget, std::iter::empty()), now + budget);

        let run_deadline = now + Duration::from_secs(1200);
        assert_eq!(
            queued_deadline(now, budget, [now + budget, run_deadline].into_iter()),
            run_deadline + budget
        );
        // A pending call whose deadline already passed doesn't shorten ours.
        let past = now.checked_sub(Duration::from_secs(5)).unwrap_or(now);
        assert_eq!(queued_deadline(now, budget, [past].into_iter()), now + budget);
    }

    #[test]
    fn only_config_writes_mark_credentials_stale() {
        assert!(affects_credentials("config.write"));
        assert!(!affects_credentials("config.read"));
        assert!(!affects_credentials("pipeline.run"));
    }

    #[test]
    fn parses_the_top_level_keys_we_need() {
        let body = "\
identity:
  blurb: |
    llm_provider: not-a-key
  name: Alice
llm_api_format: ''
llm_provider: deepseek-anthropic
llm_timeout_seconds: 600
recipient_email: alice@example.com
";
        assert_eq!(
            parse_config_hints(body),
            ConfigHints {
                llm_provider: Some("deepseek-anthropic".into()),
                llm_api_format: Some(String::new()),
                llm_timeout_seconds: Some(600),
            }
        );
    }

    #[test]
    fn strips_quotes_and_comments() {
        assert_eq!(strip_yaml_scalar(" \"openai\""), "openai");
        assert_eq!(strip_yaml_scalar(" 'openai'"), "openai");
        assert_eq!(strip_yaml_scalar(" openai  # picked in the wizard"), "openai");
        assert_eq!(strip_yaml_scalar(" ''"), "");
        assert_eq!(strip_yaml_scalar(""), "");
        assert_eq!(parse_config_hints("llm_timeout_seconds: lots\n").llm_timeout_seconds, None);
    }

    #[test]
    fn active_provider_picks_the_slug_and_auth_kind() {
        let preset = ConfigHints { llm_provider: Some("openai".into()), ..Default::default() };
        assert_eq!(preset.active_provider(), Some(("openai".into(), false)));

        let cli = ConfigHints { llm_provider: Some("claude-code-oauth".into()), ..Default::default() };
        assert_eq!(cli.active_provider(), Some(("claude-code-oauth".into(), true)));

        let custom = ConfigHints {
            llm_provider: Some(String::new()),
            llm_api_format: Some("anthropic_http".into()),
            ..Default::default()
        };
        assert_eq!(custom.active_provider(), Some(("custom".into(), false)));

        assert_eq!(ConfigHints::default().active_provider(), None);
    }

    #[test]
    fn exports_only_the_active_providers_key() {
        let store = |slug: &str| match slug {
            "deepseek-anthropic" => Some(" sk-deepseek \n".to_string()),
            "openai" => Some("sk-openai".to_string()),
            "claude" => Some("sk-ant-oat01-legacy".to_string()),
            _ => None,
        };
        assert_eq!(
            credential_env_from(Some(("deepseek-anthropic".into(), false)), store),
            vec![("HYACINE_LLM_API_KEY", "sk-deepseek".to_string())]
        );
    }

    #[test]
    fn falls_back_to_legacy_cli_slots_as_cli_tokens_only() {
        let store = |slug: &str| (slug == "claude").then(|| "sk-ant-oat01-legacy".to_string());
        // Active API-key provider with an empty slot: the legacy token is
        // only ever exported for the `claude` CLI, never as the API key.
        assert_eq!(
            credential_env_from(Some(("groq".into(), false)), store),
            vec![
                ("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-legacy".to_string()),
                ("HYACINE_CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-legacy".to_string()),
            ]
        );
        assert!(credential_env_from(None, |_: &str| None).is_empty());
        assert!(credential_env_from(None, |_: &str| Some("  ".into())).is_empty());
    }

    #[test]
    fn sidecar_env_carries_root_encoding_and_credentials() {
        let mut env: HashMap<String, String> = HashMap::from([
            ("ANTHROPIC_API_KEY".into(), "stale".into()),
            ("ANTHROPIC_AUTH_TOKEN".into(), "stale".into()),
            ("PATH".into(), "/usr/bin".into()),
        ]);
        let root = PathBuf::from("/data/com.hyacine.desktop");
        apply_sidecar_env(
            &mut env,
            Some(&root),
            &[("HYACINE_LLM_API_KEY", "sk-new".to_string())],
        );
        assert_eq!(env["HYACINE_REPO_ROOT"], root.display().to_string());
        assert_eq!(env["PYTHONUTF8"], "1");
        assert_eq!(env["PYTHONIOENCODING"], "utf-8");
        assert_eq!(env["HYACINE_LLM_API_KEY"], "sk-new");
        assert_eq!(env["PATH"], "/usr/bin");
        assert!(!env.contains_key("ANTHROPIC_API_KEY"));
        assert!(!env.contains_key("ANTHROPIC_AUTH_TOKEN"));
    }

    #[test]
    fn explicit_repo_root_is_left_alone() {
        let mut env: HashMap<String, String> =
            HashMap::from([("HYACINE_REPO_ROOT".into(), "/src/hyacine".into())]);
        apply_sidecar_env(&mut env, Some(Path::new("/src/hyacine")), &[]);
        assert_eq!(env["HYACINE_REPO_ROOT"], "/src/hyacine");

        // Blank counts as unset, as in config.py.
        let mut env: HashMap<String, String> =
            HashMap::from([("HYACINE_REPO_ROOT".into(), "  ".into())]);
        apply_sidecar_env(&mut env, Some(Path::new("/data")), &[]);
        assert_eq!(env["HYACINE_REPO_ROOT"], Path::new("/data").display().to_string());
    }

    #[test]
    fn repo_root_override_matches_config_py() {
        let home = Some(PathBuf::from("/home/alice"));
        assert_eq!(repo_root_override(None, home.clone()), None);
        assert_eq!(repo_root_override(Some("  ".into()), home.clone()), None);
        assert_eq!(
            repo_root_override(Some(" /srv/hyacine ".into()), home.clone()),
            Some(PathBuf::from("/srv/hyacine"))
        );
        assert_eq!(
            repo_root_override(Some("~/hyacine".into()), home.clone()),
            Some(PathBuf::from("/home/alice").join("hyacine"))
        );
        assert_eq!(
            repo_root_override(Some("~".into()), home),
            Some(PathBuf::from("/home/alice"))
        );
    }
}
