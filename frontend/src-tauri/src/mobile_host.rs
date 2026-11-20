pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            crate::standalone_http::standalone_http_request,
            crate::standalone_http::standalone_http_cancel,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Shinsekai mobile shell");
}
