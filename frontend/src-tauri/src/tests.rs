use std::{
    env, fs,
    io::{Read, Write},
    net::TcpListener,
    path::PathBuf,
    thread,
    time::{SystemTime, UNIX_EPOCH},
};

use crate::bridge::{send_bridge_agent_close, send_bridge_chat_close};
use crate::frontend_protocol::{
    app_window_url, chat_window_url, live_chat_frontend_url, live_frontend_origin_for_platform,
    live_frontend_reload_targets, live_frontend_url, resolve_published_frontend_dist,
    resolve_static_request_path, FRONTEND_DIST_MARKER, FRONTEND_DIST_RELEASES,
};
use crate::paths::{app_root_from_executable, app_root_from_resource_dir};
use crate::runtime;
use crate::runtime_commands::{
    phase_after_runtime_scan, project_root_setup_log_event, should_bootstrap_runtime,
};
use crate::state::{
    is_truthy_env_value, sanitize_restart_debug_log_message, DesktopRuntimePhase, BRIDGE_HOST,
};
use crate::window_controls::{
    chat_window_open_plan_for_windows, compute_mini_dock_side, default_mini_window_position,
    desired_mini_input_global_shortcut,
};
use crate::{
    resolve_main_window_initial_size, MAIN_WINDOW_DEFAULT_HEIGHT, MAIN_WINDOW_DEFAULT_WIDTH,
    MAIN_WINDOW_MIN_HEIGHT, MAIN_WINDOW_MIN_WIDTH,
};

#[test]
fn runtime_backend_console_truthy_values_are_case_insensitive() {
    for value in ["1", "true", "TRUE", "yes", "Yes", "on", "ON"] {
        assert!(
            is_truthy_env_value(value),
            "expected {value:?} to be truthy"
        );
    }
}

#[test]
fn runtime_backend_console_rejects_other_values() {
    for value in ["", "0", "false", "off", "y", " true "] {
        assert!(
            !is_truthy_env_value(value),
            "expected {value:?} to be falsey"
        );
    }
}

#[test]
fn resolve_published_frontend_dist_uses_current_marker() {
    let root = temp_test_dir("published-dist");
    let raw_dist = root.join("frontend").join("dist");
    let release = root
        .join("frontend")
        .join(FRONTEND_DIST_RELEASES)
        .join("v2");
    fs::create_dir_all(&raw_dist).unwrap();
    fs::create_dir_all(&release).unwrap();
    fs::write(raw_dist.join("index.html"), "old").unwrap();
    fs::write(release.join("index.html"), "new").unwrap();
    fs::write(
        root.join("frontend").join(FRONTEND_DIST_MARKER),
        format!("{FRONTEND_DIST_RELEASES}/v2\n"),
    )
    .unwrap();

    assert_eq!(
        resolve_published_frontend_dist(&raw_dist),
        release.canonicalize().unwrap()
    );
    let _ = fs::remove_dir_all(root);
}

#[test]
fn resolve_static_request_path_rejects_parent_and_backslash_segments() {
    let root = PathBuf::from("/tmp/frontend-dist");

    assert_eq!(
        resolve_static_request_path(&root, "/web-assets/app.js").unwrap(),
        root.join("web-assets").join("app.js")
    );
    assert!(resolve_static_request_path(&root, "/../secret").is_none());
    assert!(resolve_static_request_path(&root, "/web-assets\\secret.js").is_none());
}

#[test]
fn app_root_from_executable_uses_executable_parent() {
    let executable = PathBuf::from("/opt/Shinsekai/shinsekai");

    assert_eq!(
        app_root_from_executable(&executable).unwrap(),
        PathBuf::from("/opt/Shinsekai")
    );
}

#[test]
fn app_root_from_resource_dir_unwraps_resources_directory() {
    let resource_dir = PathBuf::from("/opt/Shinsekai/resources");

    assert_eq!(
        app_root_from_resource_dir(&resource_dir).unwrap(),
        PathBuf::from("/opt/Shinsekai")
    );
}

#[test]
fn project_root_conflict_defers_runtime_bootstrap() {
    assert!(!should_bootstrap_runtime(true));
    assert!(should_bootstrap_runtime(false));
}

#[test]
fn unresolved_project_root_is_not_logged_as_a_recovery_source() {
    assert_eq!(
        project_root_setup_log_event(true),
        "setup awaiting project-root selection"
    );
    assert_eq!(project_root_setup_log_event(false), "setup resolved");
}

#[test]
fn restart_debug_log_messages_cannot_inject_additional_lines() {
    assert_eq!(
        sanitize_restart_debug_log_message("safe\r\nsetup resolved injected\0"),
        "safe\\r\\nsetup resolved injected\\0"
    );
}

#[test]
fn runtime_scan_keeps_ready_state_when_bridge_is_running() {
    let phase = phase_after_runtime_scan(true, runtime_scan_view(Some("python-ready")));

    match phase {
        DesktopRuntimePhase::Ready { view: Some(view) } => {
            assert_eq!(view.selected_candidate_id.as_deref(), Some("python-ready"));
        }
        _ => panic!("running bridge with a ready candidate should stay ready"),
    }
}

#[test]
fn runtime_scan_enters_guided_action_when_no_ready_candidate_exists() {
    let phase = phase_after_runtime_scan(true, runtime_scan_view(None));

    match phase {
        DesktopRuntimePhase::NeedsAction { view } => {
            assert_eq!(view.message.as_deref(), Some("needs runtime action"));
        }
        _ => panic!("scan without a ready candidate should enter runtime guidance"),
    }
}

#[test]
fn window_urls_encode_bridge_and_route() {
    assert_eq!(
        app_window_url(8787, "token-1"),
        "index.html?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787&shinsekai_bridge_token=token-1#/settings/api"
    );
    assert_eq!(
        chat_window_url(8787, "token-1"),
        "index.html?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787&shinsekai_bridge_token=token-1#/chat-stage"
    );
}

#[test]
fn live_frontend_urls_target_expected_routes() {
    let main = live_frontend_url(8787, "token-1");
    let chat = live_chat_frontend_url(8787, "token-1");
    let expected_origin = live_frontend_origin_for_platform(cfg!(windows));

    assert!(main.starts_with(&format!(
        "{expected_origin}/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787"
    )));
    assert!(main.contains("shinsekai_bridge_token=token-1"));
    assert!(main.contains("#/settings/api"));
    assert!(chat.starts_with(&format!(
        "{expected_origin}/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787"
    )));
    assert!(chat.contains("shinsekai_bridge_token=token-1"));
    assert!(chat.contains("#/chat-stage"));
}

#[test]
fn live_frontend_origin_matches_tauri_custom_protocol_mapping() {
    assert_eq!(
        live_frontend_origin_for_platform(true),
        "http://shinsekai.localhost"
    );
    assert_eq!(
        live_frontend_origin_for_platform(false),
        "shinsekai://localhost"
    );
}

#[test]
fn live_frontend_reload_targets_cover_main_and_chat_windows() {
    let targets = live_frontend_reload_targets(8787, "token-1");

    assert_eq!(targets[0].0, "main");
    assert!(targets[0].1.contains("#/settings/api"));
    assert_eq!(targets[1].0, "chat");
    assert!(targets[1].1.contains("#/chat-stage"));
    assert!(targets[1].1.starts_with(&format!(
        "{}/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787",
        live_frontend_origin_for_platform(cfg!(windows))
    )));
    assert!(targets[1].1.contains("shinsekai_bridge_token=token-1"));
    assert_eq!(targets[2].0, "reminders");
    assert!(targets[2].1.contains("#/reminders"));
}

#[test]
fn windows_chat_window_open_plan_avoids_webview_timing_hazards() {
    let plan = chat_window_open_plan_for_windows(true);

    assert!(plan.defer_command);
    assert!(!plan.navigate_after_create);
    assert!(!plan.focus_after_show);
}

#[test]
fn non_windows_chat_window_open_plan_keeps_existing_live_navigation() {
    let plan = chat_window_open_plan_for_windows(false);

    assert!(!plan.defer_command);
    assert!(plan.navigate_after_create);
    assert!(plan.focus_after_show);
}

#[test]
fn mini_dock_side_flips_on_right_portion_of_monitor() {
    assert_eq!(compute_mini_dock_side(400.0, 0.0, 1920.0), "left");
    assert_eq!(compute_mini_dock_side(1100.0, 0.0, 1920.0), "left");
    assert_eq!(compute_mini_dock_side(1300.0, 0.0, 1920.0), "right");
    // Secondary monitor with negative X offset:
    assert_eq!(compute_mini_dock_side(-300.0, -1920.0, 1920.0), "right");
    assert_eq!(compute_mini_dock_side(-1500.0, -1920.0, 1920.0), "left");
}

#[test]
fn default_mini_window_position_places_avatar_in_upper_right_region() {
    let pos = default_mini_window_position((0, 0), (1920, 1080), (640, 340));
    let center_x = f64::from(pos.x) + 320.0;
    assert_eq!(compute_mini_dock_side(center_x, 0.0, 1920.0), "right");
    assert!(pos.y >= 16);
}

#[test]
fn desired_mini_input_shortcut_requires_active_mini_chat_window() {
    assert_eq!(
        desired_mini_input_global_shortcut(true, true, Some(" Alt+Q ")),
        Some("Alt+Q".to_string())
    );
    assert_eq!(
        desired_mini_input_global_shortcut(false, true, Some("Alt+Q")),
        None
    );
    assert_eq!(
        desired_mini_input_global_shortcut(true, false, Some("Alt+Q")),
        None
    );
    assert_eq!(
        desired_mini_input_global_shortcut(true, true, Some("   ")),
        None
    );
    assert_eq!(desired_mini_input_global_shortcut(true, true, None), None);

    #[cfg(desktop)]
    for accelerator in [
        "Alt+Q",
        "Ctrl+Shift+Space",
        "Super+Slash",
        "F7",
        "Alt+Backquote",
    ] {
        assert!(
            accelerator
                .parse::<tauri_plugin_global_shortcut::Shortcut>()
                .is_ok(),
            "expected {accelerator} to parse as a valid global shortcut"
        );
    }
}

#[test]
fn send_bridge_chat_close_posts_local_close_request() {
    let listener = TcpListener::bind((BRIDGE_HOST, 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    let handle = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut buffer = [0_u8; 1024];
        let read = stream.read(&mut buffer).unwrap();
        let request = String::from_utf8_lossy(&buffer[..read]).to_string();
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
            .unwrap();
        request
    });

    send_bridge_chat_close(port, "token-1").unwrap();

    let request = handle.join().unwrap();
    assert!(request.starts_with("POST /api/chat/close HTTP/1.1\r\n"));
    assert!(request.contains("Host: 127.0.0.1\r\n"));
    assert!(request.contains("Content-Type: application/json\r\n"));
    assert!(request.contains("X-Shinsekai-Bridge-Token: token-1\r\n"));
    assert!(request.ends_with("\r\n\r\n{}"));
}

#[test]
fn send_bridge_agent_close_posts_authenticated_runtime_shutdown() {
    let listener = TcpListener::bind((BRIDGE_HOST, 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    let handle = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut buffer = [0_u8; 1024];
        let read = stream.read(&mut buffer).unwrap();
        let request = String::from_utf8_lossy(&buffer[..read]).to_string();
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
            .unwrap();
        request
    });
    send_bridge_agent_close(port, "agent-token").unwrap();
    let request = handle.join().unwrap();
    assert!(request.starts_with("POST /api/agent/runtime/stop HTTP/1.1\r\n"));
    assert!(request.contains("X-Shinsekai-Bridge-Token: agent-token\r\n"));
    assert!(request.ends_with("\r\n\r\n{}"));
}

#[test]
fn main_window_default_size_preserves_legacy_aspect_ratio() {
    let legacy_ratio = 1180.0_f64 / 780.0_f64;
    let default_ratio = MAIN_WINDOW_DEFAULT_WIDTH / MAIN_WINDOW_DEFAULT_HEIGHT;
    assert!((default_ratio - legacy_ratio).abs() < 1e-9);
    assert_eq!(
        resolve_main_window_initial_size(None),
        (MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT)
    );
    assert_eq!(
        resolve_main_window_initial_size(Some((1920.0, 1040.0))),
        (MAIN_WINDOW_DEFAULT_WIDTH, MAIN_WINDOW_DEFAULT_HEIGHT)
    );
}

#[test]
fn main_window_initial_size_scales_proportionally_for_smaller_work_areas() {
    let legacy_ratio = 1180.0_f64 / 780.0_f64;
    let (width, height) = resolve_main_window_initial_size(Some((1536.0, 825.0)));
    assert!(width > 1180.0);
    assert!(height > 780.0);
    assert!(width <= 1536.0 * 0.96 + 1.0);
    assert!(height <= 825.0 * 0.96 + 1.0);
    assert!(((width / height) - legacy_ratio).abs() < 0.01);

    assert_eq!(
        resolve_main_window_initial_size(Some((700.0, 500.0))),
        (MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
    );
}

fn runtime_scan_view(selected_candidate_id: Option<&str>) -> runtime::RuntimeScanView {
    runtime::RuntimeScanView {
        selected_candidate_id: selected_candidate_id.map(ToString::to_string),
        recommended_action: Some(runtime::RuntimeRepairActionKind::Start),
        candidates: Vec::new(),
        message: Some("needs runtime action".to_string()),
    }
}

fn temp_test_dir(label: &str) -> PathBuf {
    let token = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    env::temp_dir().join(format!(
        "shinsekai-tauri-test-{label}-{}-{token}",
        std::process::id()
    ))
}
