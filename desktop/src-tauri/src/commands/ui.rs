//! Small UI-side conveniences — launch-at-login toggle, etc.
//!
//! Launch-at-login across platforms is fiddly (LSUIElement on macOS, Run
//! registry key on Windows, .desktop file under ~/.config/autostart on Linux).
//! We stub the command here so the frontend has a stable entry point and we
//! can fill the platform-specific logic in later without breaking the UI.

use crate::error::AppResult;

#[tauri::command]
pub async fn ui_set_startup(enabled: bool) -> AppResult<()> {
    tracing::info!(enabled, "ui_set_startup (stub)");
    // TODO: wire tauri-plugin-autostart once upstream settles.
    Ok(())
}
