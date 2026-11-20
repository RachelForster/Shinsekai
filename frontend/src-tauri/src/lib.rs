pub mod standalone_http;

#[cfg(desktop)]
include!("desktop_host.rs");

#[cfg(mobile)]
mod mobile_host;

#[cfg(mobile)]
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    mobile_host::run();
}
