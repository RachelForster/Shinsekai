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
    let mut command = python_command(&source_root)?;
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

fn python_command(project_root: &Path) -> DesktopResult<Command> {
    if let Some(raw) = env::var_os("SHINSEKAI_PYTHON") {
        return Ok(Command::new(raw));
    }

    let embedded_candidates = [
        project_root.join("runtime").join("bin").join("python3"),
        project_root.join("runtime").join("bin").join("python"),
        project_root.join("runtime").join("python.exe"),
    ];
    for candidate in embedded_candidates {
        if candidate.is_file() {
            return Ok(Command::new(candidate));
        }
    }

    let conda_env = env::var("SHINSEKAI_CONDA_ENV").unwrap_or_else(|_| "shinsekai".to_string());
    if let Some(conda_python) = find_conda_env_python(&conda_env) {
        return Ok(Command::new(conda_python));
    }

    for name in python_candidate_names() {
        if let Some(path) = find_on_path(name) {
            return Ok(Command::new(path));
        }
    }

    Err("no Python runtime found; set SHINSEKAI_PYTHON, provide runtime/, or install the shinsekai conda env".into())
}

fn sanitize_python_environment(command: &mut Command) {
    command.env_remove("PYTHONHOME").env_remove("PYTHONPATH");

    if env::var_os("APPIMAGE").is_some() || env::var_os("APPDIR").is_some() {
        command.env_remove("LD_LIBRARY_PATH");
    }
}

#[cfg(windows)]
fn python_candidate_names() -> &'static [&'static str] {
    &["python.exe", "python3.exe", "py.exe"]
}

#[cfg(not(windows))]
fn python_candidate_names() -> &'static [&'static str] {
    &["python3", "python"]
}

fn find_on_path(name: &str) -> Option<PathBuf> {
    let direct = PathBuf::from(name);
    if direct.is_file() {
        return Some(direct);
    }

    let paths = env::var_os("PATH")?;
    let candidates = executable_names(name);
    env::split_paths(&paths).find_map(|path| {
        candidates
            .iter()
            .map(|candidate| path.join(candidate))
            .find(|candidate| candidate.is_file())
    })
}

fn find_conda_env_python(env_name: &str) -> Option<PathBuf> {
    if let Some(prefix) = env_path("CONDA_PREFIX") {
        if env::var("CONDA_DEFAULT_ENV").ok().as_deref() == Some(env_name) {
            if let Some(python) = python_in_prefix(&prefix) {
                return Some(python);
            }
        }
    }

    let mut roots = Vec::new();
    if let Some(conda_exe) = env_path("CONDA_EXE").or_else(|| find_on_path("conda")) {
        roots.extend(conda_roots_from_executable(&conda_exe));
    }
    roots.extend(default_conda_roots());

    roots
        .into_iter()
        .map(|root| root.join("envs").join(env_name))
        .find_map(|prefix| python_in_prefix(&prefix))
}

fn conda_roots_from_executable(conda_exe: &Path) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(parent) = conda_exe.parent() {
        if let Some(root) = parent.parent() {
            roots.push(root.to_path_buf());
        }
        if parent.file_name().and_then(|name| name.to_str()) == Some("condabin") {
            if let Some(root) = parent.parent() {
                roots.push(root.to_path_buf());
            }
        }
    }
    roots
}

fn default_conda_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(home) = home_dir() {
        roots.push(home.join("miniconda3"));
        roots.push(home.join("anaconda3"));
    }
    #[cfg(not(windows))]
    {
        roots.push(PathBuf::from("/opt/miniconda3"));
        roots.push(PathBuf::from("/opt/anaconda3"));
    }
    #[cfg(windows)]
    {
        if let Some(program_data) = env::var_os("ProgramData") {
            let program_data = PathBuf::from(program_data);
            roots.push(program_data.join("miniconda3"));
            roots.push(program_data.join("anaconda3"));
        }
    }
    roots
}

fn python_in_prefix(prefix: &Path) -> Option<PathBuf> {
    let candidates = [
        prefix.join("bin").join("python3"),
        prefix.join("bin").join("python"),
        prefix.join("python.exe"),
    ];
    candidates.into_iter().find(|candidate| candidate.is_file())
}

#[cfg(windows)]
fn executable_names(name: &str) -> Vec<String> {
    if Path::new(name).extension().is_some() {
        return vec![name.to_string()];
    }

    let pathext = env::var("PATHEXT").unwrap_or_else(|_| ".COM;.EXE;.BAT;.CMD".to_string());
    let mut names = vec![name.to_string()];
    names.extend(
        pathext
            .split(';')
            .map(str::trim)
            .filter(|ext| !ext.is_empty())
            .map(|ext| format!("{name}{ext}")),
    );
    names
}

#[cfg(not(windows))]
fn executable_names(name: &str) -> Vec<String> {
    vec![name.to_string()]
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
