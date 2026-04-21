//! Tauri entry point.
//!
//! Wires plugins, commands, and the Python sidecar state into the app builder.

mod error;
mod sidecar;
mod secrets;
mod commands;

use sidecar::SidecarState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "hyacine_desktop_lib=info,tauri=warn".into()),
        )
        .with_writer(std::io::stderr)
        .init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_process::init())
        .manage(SidecarState::new())
        .invoke_handler(tauri::generate_handler![
            commands::sidecar::sidecar_start,
            commands::sidecar::sidecar_stop,
            commands::sidecar::sidecar_rpc,
            commands::secrets::secrets_set,
            commands::secrets::secrets_has,
            commands::secrets::secrets_remove,
            commands::secrets::secrets_test_claude,
            commands::probes::rust_probe_claude,
            commands::probes::rust_probe_graph,
            commands::probes::rust_probe_sendmail,
            commands::ui::ui_set_startup,
        ])
        .setup(|app| {
            tracing::info!("Hyacine desktop starting");
            #[cfg(desktop)]
            {
                use tauri::Manager;
                let _ = app.get_webview_window("main");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Hyacine desktop");
}
