use serde_json::Value;
use tauri::{AppHandle, State};

use crate::error::AppResult;
use crate::sidecar::SidecarState;

#[tauri::command]
pub async fn sidecar_start(app: AppHandle, state: State<'_, SidecarState>) -> AppResult<()> {
    state.start(&app).await
}

#[tauri::command]
pub async fn sidecar_stop(state: State<'_, SidecarState>) -> AppResult<()> {
    state.stop().await
}

#[tauri::command]
pub async fn sidecar_rpc(
    app: AppHandle,
    method: String,
    params: Option<Value>,
    state: State<'_, SidecarState>,
) -> AppResult<Value> {
    // `rpc` starts (or restarts) the sidecar itself, so this works even when
    // it lands before the layout's `sidecar_start`.
    state
        .rpc::<Value>(&app, &method, params.unwrap_or(Value::Object(Default::default())))
        .await
}
