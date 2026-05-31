use std::{
    env,
    error::Error,
    fs,
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

mod runtime;

type DesktopResult<T> = Result<T, Box<dyn Error>>;

const BRIDGE_HOST: &str = "127.0.0.1";
const DEFAULT_BRIDGE_PORT: u16 = 8787;

struct BridgeProcess {
    child: Mutex<Option<Child>>,
}

impl BridgeProcess {
    fn new(child: Child) -> Self {
        Self {
            child: Mutex::new(Some(child)),
        }
    }
}

impl Drop for BridgeProcess {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut child) = child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

struct BridgeLaunch {
    child: Child,
    port: u16,
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let bridge = start_bridge(app)?;
            let url = format!("http://{BRIDGE_HOST}:{}#/settings/api", bridge.port);
            app.manage(BridgeProcess::new(bridge.child));

            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse()?))
                .title("Shinsekai")
                .inner_size(1180.0, 780.0)
                .min_inner_size(860.0, 620.0)
                .center()
                .on_navigation(move |target| {
                    target.host_str() == Some(BRIDGE_HOST)
                        && target.port_or_known_default() == Some(bridge.port)
                })
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Shinsekai desktop shell");
}

fn start_bridge(app: &tauri::App) -> DesktopResult<BridgeLaunch> {
    let source_root = resolve_source_root(app)?;
    let project_root = resolve_project_root(app, &source_root)?;
    let frontend_dist = resolve_frontend_dist(&source_root)?;
    let port = choose_bridge_port()?;
    let runtime = runtime::resolve_python_runtime(app, &source_root)?;
    println!("Using Shinsekai Python runtime: {}", runtime.description);
    let mut command = runtime.command;
    sanitize_python_environment(&mut command);

    command
        .arg(source_root.join("frontend_bridge.py"))
        .arg("--host")
        .arg(BRIDGE_HOST)
        .arg("--port")
        .arg(port.to_string())
        .arg("--project-root")
        .arg(&project_root)
        .arg("--frontend-dist")
        .arg(&frontend_dist)
        .current_dir(&source_root);

    let mut child = command.spawn().map_err(|error| {
        format!(
            "failed to start Shinsekai Python bridge from {}: {error}",
            source_root.display()
        )
    })?;

    wait_for_bridge(&mut child, port)?;
    Ok(BridgeLaunch { child, port })
}

fn resolve_source_root(app: &tauri::App) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_SOURCE_ROOT") {
        if has_bridge(&root) {
            return Ok(root);
        }
        return Err(format!(
            "SHINSEKAI_SOURCE_ROOT does not contain frontend_bridge.py: {}",
            root.display()
        )
        .into());
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        if has_bridge(&resource_dir) {
            return Ok(resource_dir);
        }
    }

    if let Some(root) = dev_project_root() {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    let exe_dir = env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    if let Some(root) = exe_dir {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    Err("could not locate Shinsekai application resources; set SHINSEKAI_SOURCE_ROOT".into())
}

fn resolve_project_root(app: &tauri::App, source_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_PROJECT_ROOT") {
        fs::create_dir_all(&root)?;
        return Ok(root);
    }

    if dev_project_root().as_deref() == Some(source_root) {
        return Ok(source_root.to_path_buf());
    }

    let data_dir = app.path().app_data_dir()?.join("project");
    fs::create_dir_all(&data_dir)?;
    Ok(data_dir)
}

fn dev_project_root() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent()?.parent().map(Path::to_path_buf)
}

fn has_bridge(root: &Path) -> bool {
    root.join("frontend_bridge.py").is_file()
}

fn resolve_frontend_dist(project_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(dist) = env_path("SHINSEKAI_FRONTEND_DIST") {
        if dist.join("index.html").is_file() {
            return Ok(dist);
        }
        return Err(format!(
            "SHINSEKAI_FRONTEND_DIST does not contain index.html: {}",
            dist.display()
        )
        .into());
    }

    let dist = project_root.join("frontend").join("dist");
    if dist.join("index.html").is_file() {
        return Ok(dist);
    }

    Err(format!(
        "built frontend not found at {}; run `pnpm build` in frontend first",
        dist.display()
    )
    .into())
}

fn env_path(name: &str) -> Option<PathBuf> {
    env::var_os(name)
        .map(PathBuf::from)
        .map(|path| path.expand_home())
        .map(|path| path.canonicalize().unwrap_or(path))
}

fn sanitize_python_environment(command: &mut Command) {
    command.env_remove("PYTHONHOME").env_remove("PYTHONPATH");

    if env::var_os("APPIMAGE").is_some() || env::var_os("APPDIR").is_some() {
        command.env_remove("LD_LIBRARY_PATH");
    }
}

fn choose_bridge_port() -> DesktopResult<u16> {
    if let Ok(raw) = env::var("SHINSEKAI_BRIDGE_PORT") {
        let port = raw
            .parse::<u16>()
            .map_err(|_| format!("SHINSEKAI_BRIDGE_PORT is not a valid port: {raw}"))?;
        return Ok(port);
    }

    if TcpListener::bind((BRIDGE_HOST, DEFAULT_BRIDGE_PORT)).is_ok() {
        return Ok(DEFAULT_BRIDGE_PORT);
    }

    let listener = TcpListener::bind((BRIDGE_HOST, 0))?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_bridge(child: &mut Child, port: u16) -> DesktopResult<()> {
    let addr: SocketAddr = format!("{BRIDGE_HOST}:{port}").parse()?;
    let started = Instant::now();
    let timeout = Duration::from_secs(45);

    while started.elapsed() < timeout {
        if let Some(status) = child.try_wait()? {
            return Err(format!("Python bridge exited before startup completed: {status}").into());
        }

        if TcpStream::connect_timeout(&addr, Duration::from_millis(120)).is_ok() {
            return Ok(());
        }

        thread::sleep(Duration::from_millis(120));
    }

    Err(format!("timed out waiting for Python bridge on http://{BRIDGE_HOST}:{port}").into())
}

trait ExpandHome {
    fn expand_home(self) -> Self;
}

impl ExpandHome for PathBuf {
    fn expand_home(self) -> Self {
        let raw = self.as_os_str().to_string_lossy();
        if raw == "~" {
            return home_dir().unwrap_or(self);
        }
        if let Some(rest) = raw.strip_prefix("~/") {
            if let Some(home) = home_dir() {
                return home.join(rest);
            }
        }
        self
    }
}

fn home_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        env::var_os("USERPROFILE").map(PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        env::var_os("HOME").map(PathBuf::from)
    }
}
