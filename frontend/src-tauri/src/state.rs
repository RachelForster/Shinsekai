use std::{
    env,
    error::Error,
    fs::OpenOptions,
    io::Write,
    path::PathBuf,
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{State, WebviewWindow};

use crate::{
    bridge::BridgeProcess,
    desktop_files::{browse_desktop_files, DesktopFileBrowserSnapshot},
    project_root, runtime,
};

pub(crate) type DesktopResult<T> = Result<T, Box<dyn Error>>;

pub(crate) const BRIDGE_HOST: &str = "127.0.0.1";
pub(crate) const DEFAULT_BRIDGE_PORT: u16 = 8787;
pub(crate) const RESTART_DEBUG_LOG_FILE: &str = "shinsekai-restart-debug.log";
#[cfg_attr(not(windows), allow(dead_code))]
const SHOW_BACKEND_CONSOLE_ENV: &str = "SHINSEKAI_SHOW_BACKEND_CONSOLE";

#[derive(Clone)]
pub(crate) enum DesktopRuntimePhase {
    Checking {
        view: Option<runtime::RuntimeScanView>,
    },
    NeedsAction {
        view: runtime::RuntimeScanView,
    },
    Updating {
        view: Option<runtime::RuntimeScanView>,
    },
    Ready {
        view: Option<runtime::RuntimeScanView>,
    },
    Error {
        message: String,
        view: Option<runtime::RuntimeScanView>,
        dependency_install_failed: bool,
    },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopRuntimeView {
    status: &'static str,
    message: Option<String>,
    bridge_url: String,
    manual_install_command: Option<String>,
    selected_candidate_id: Option<String>,
    recommended_action: Option<runtime::RuntimeRepairActionKind>,
    candidates: Vec<runtime::RuntimeCandidateView>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopRuntimeProgress {
    pub(crate) phase: &'static str,
    pub(crate) candidate_id: Option<String>,
    pub(crate) source: Option<String>,
    pub(crate) downloaded: Option<u64>,
    pub(crate) total: Option<u64>,
    pub(crate) speed_bytes_per_sec: Option<f64>,
    pub(crate) message: Option<String>,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct SavedChatWindowBounds {
    pub(crate) position: tauri::PhysicalPosition<i32>,
    pub(crate) size: tauri::PhysicalSize<u32>,
    pub(crate) maximized: bool,
}

#[derive(Default)]
pub(crate) struct ChatWindowModeState {
    pub(crate) mini_active: bool,
    pub(crate) mini_input_shortcut: Option<String>,
    pub(crate) normal_bounds: Option<SavedChatWindowBounds>,
    pub(crate) mini_position: Option<tauri::PhysicalPosition<i32>>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopMiniInputShortcutStatus {
    pub(crate) registered: bool,
    pub(crate) error: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopMiniWindowLayout {
    pub(crate) dock_side: &'static str,
}

pub(crate) fn is_portable_bundle(app_root: &std::path::Path) -> bool {
    app_root
        .join(project_root::PORTABLE_ROOT_MARKER_FILE)
        .is_file()
}

pub(crate) struct DesktopState {
    pub(crate) source_root: PathBuf,
    pub(crate) project_root: PathBuf,
    pub(crate) project_root_controller: project_root::ProjectRootController,
    pub(crate) app_root: PathBuf,
    pub(crate) frontend_dist: PathBuf,
    pub(crate) bridge_port: u16,
    pub(crate) bridge_auth_token: String,
    pub(crate) bridge: Mutex<Option<BridgeProcess>>,
    pub(crate) runtime: Mutex<DesktopRuntimePhase>,
    pub(crate) chat_window_mode: Mutex<ChatWindowModeState>,
    pub(crate) mini_shortcut_sync_lock: Mutex<()>,
}

impl DesktopState {
    pub(crate) fn new(
        source_root: PathBuf,
        project_root: PathBuf,
        project_root_controller: project_root::ProjectRootController,
        app_root: PathBuf,
        frontend_dist: PathBuf,
        bridge_port: u16,
        bridge_auth_token: String,
    ) -> Self {
        Self {
            source_root,
            project_root,
            project_root_controller,
            app_root,
            frontend_dist,
            bridge_port,
            bridge_auth_token,
            bridge: Mutex::new(None),
            runtime: Mutex::new(DesktopRuntimePhase::Checking { view: None }),
            chat_window_mode: Mutex::new(ChatWindowModeState::default()),
            mini_shortcut_sync_lock: Mutex::new(()),
        }
    }

    pub(crate) fn reset_chat_window_session_bounds(&self) {
        if let Ok(mut mode) = self.chat_window_mode.lock() {
            mode.mini_active = false;
            mode.mini_input_shortcut = None;
            mode.normal_bounds = None;
        }
    }

    pub(crate) fn is_portable(&self) -> bool {
        is_portable_bundle(&self.app_root)
    }

    pub(crate) fn bridge_url(&self) -> String {
        format!("http://{BRIDGE_HOST}:{}", self.bridge_port)
    }

    pub(crate) fn set_runtime(&self, phase: DesktopRuntimePhase) {
        if let Ok(mut runtime) = self.runtime.lock() {
            *runtime = phase;
        }
    }

    pub(crate) fn take_bridge(&self) -> Option<BridgeProcess> {
        self.bridge.lock().ok()?.take()
    }

    pub(crate) fn has_bridge(&self) -> bool {
        self.bridge
            .lock()
            .map(|bridge| bridge.is_some())
            .unwrap_or(false)
    }

    pub(crate) fn bridge_candidate_id(&self) -> Option<String> {
        self.bridge
            .lock()
            .ok()?
            .as_ref()
            .and_then(|bridge| bridge.candidate_id.clone())
    }

    pub(crate) fn runtime_view(&self) -> DesktopRuntimeView {
        let phase = self
            .runtime
            .lock()
            .map(|runtime| runtime.clone())
            .unwrap_or_else(|_| DesktopRuntimePhase::Error {
                message: "runtime state lock is poisoned".to_string(),
                view: None,
                dependency_install_failed: false,
            });
        let (status, message, scan_view, dependency_install_failed) = match phase {
            DesktopRuntimePhase::Checking { view } => ("checking", None, view, false),
            DesktopRuntimePhase::NeedsAction { view } => {
                ("needsAction", view.message.clone(), Some(view), false)
            }
            DesktopRuntimePhase::Updating { view } => ("updating", None, view, false),
            DesktopRuntimePhase::Ready { view } => ("ready", None, view, false),
            DesktopRuntimePhase::Error {
                message,
                view,
                dependency_install_failed,
            } => ("error", Some(message), view, dependency_install_failed),
        };
        let scanned_selected_candidate_id = scan_view
            .as_ref()
            .and_then(|view| view.selected_candidate_id.clone());
        let recommended_action = scan_view.as_ref().and_then(|view| view.recommended_action);
        let mut candidates = scan_view
            .map(|view| view.candidates)
            .unwrap_or_else(Vec::new);
        let bridge_candidate_id = self.bridge_candidate_id();
        let selected_candidate_id = bridge_candidate_id
            .filter(|id| candidates.iter().any(|candidate| candidate.id == *id))
            .or(scanned_selected_candidate_id);
        for candidate in &mut candidates {
            candidate.selected = Some(&candidate.id) == selected_candidate_id.as_ref();
        }
        let manual_install_command = dependency_install_failed
            .then(|| {
                runtime::manual_install_command(
                    &self.source_root,
                    candidates
                        .iter()
                        .find(|candidate| candidate.selected)
                        .or_else(|| candidates.first()),
                )
            })
            .flatten();
        DesktopRuntimeView {
            status,
            message,
            bridge_url: self.bridge_url(),
            manual_install_command,
            selected_candidate_id,
            recommended_action,
            candidates,
        }
    }
}

#[derive(Default)]
pub(crate) struct PluginChatWake(pub(crate) Mutex<Option<String>>);

pub(crate) fn plugin_chat_wake_argument(
    args: impl IntoIterator<Item = String>,
) -> Option<String> {
    args.into_iter().find_map(|arg| {
        let id = arg.strip_prefix("--plugin-chat=")?;
        let (plugin, action) = id.split_once('/')?;
        if [plugin, action].iter().all(|part| {
            !part.is_empty()
                && part.len() <= 128
                && part
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'-'))
        }) {
            Some(id.to_owned())
        } else {
            None
        }
    })
}

#[tauri::command]
pub(crate) fn desktop_take_plugin_chat_wake(
    window: WebviewWindow,
    state: State<'_, PluginChatWake>,
) -> Option<String> {
    if window.label() != "main" {
        return None;
    }
    state.0.lock().ok()?.take()
}

pub(crate) fn restart_debug_log_path() -> PathBuf {
    env::var_os("SHINSEKAI_RESTART_LOG")
        .map(PathBuf::from)
        .unwrap_or_else(|| env::temp_dir().join(RESTART_DEBUG_LOG_FILE))
}

pub(crate) fn restart_debug_log(message: impl AsRef<str>) {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| format!("{}.{:03}", duration.as_secs(), duration.subsec_millis()))
        .unwrap_or_else(|_| "time-error".to_string());
    let message = sanitize_restart_debug_log_message(message.as_ref());
    let line = format!(
        "ts={} pid={} component=desktop {}\n",
        timestamp,
        std::process::id(),
        message
    );
    eprint!("[restart-debug] {}", line);
    if let Ok(mut file) = OpenOptions::new()
        .append(true)
        .create(true)
        .open(restart_debug_log_path())
    {
        let _ = file.write_all(line.as_bytes());
    }
}

pub(crate) fn sanitize_restart_debug_log_message(message: &str) -> String {
    message
        .replace('\0', "\\0")
        .replace('\r', "\\r")
        .replace('\n', "\\n")
}

#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn show_backend_console() -> bool {
    env::var(SHOW_BACKEND_CONSOLE_ENV)
        .map(|value| is_truthy_env_value(&value))
        .unwrap_or(false)
}

#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn is_truthy_env_value(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}

fn bytes_to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 0x0f) as usize] as char);
    }
    result
}

pub(crate) fn generate_bridge_auth_token() -> DesktopResult<String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes)
        .map_err(|error| format!("failed to generate bridge auth token: {error}"))?;
    Ok(bytes_to_hex(&bytes))
}

#[tauri::command]
pub(crate) fn desktop_project_root_status(
    state: State<'_, DesktopState>,
) -> project_root::ProjectRootStatus {
    state.project_root_controller.status()
}

#[tauri::command]
pub(crate) fn desktop_project_root_select(
    state: State<'_, DesktopState>,
    path: String,
) -> Result<project_root::ProjectRootStatus, String> {
    restart_debug_log(format!(
        "desktop_project_root_select command received path={path}"
    ));
    state.project_root_controller.select(&path)
}

#[tauri::command]
pub(crate) fn desktop_restart_debug_log(message: String) {
    restart_debug_log(format!("frontend {}", message));
}

#[tauri::command]
pub(crate) fn desktop_files_browse(
    state: State<'_, DesktopState>,
    path: Option<String>,
    show_hidden: Option<bool>,
) -> Result<DesktopFileBrowserSnapshot, String> {
    browse_desktop_files(
        &state.project_root,
        &state.app_root,
        path.as_deref(),
        show_hidden.unwrap_or(false),
    )
    .map_err(|error| error.to_string())
}
