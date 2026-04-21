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
    method: String,
    params: Option<Value>,
    state: State<'_, SidecarState>,
) -> AppResult<Value> {
    state
        .rpc::<Value>(&method, params.unwrap_or(Value::Object(Default::default())))
        .await
}
