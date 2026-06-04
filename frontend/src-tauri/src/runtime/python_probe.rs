use std::{
    env, fs,
    path::{Path, PathBuf},
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{Manager, Runtime};

use super::manifest::{env_path, home_dir};

pub const DEFAULT_CONDA_ENV: &str = "shinsekai";
const RUNTIME_PREFERENCE_FILE: &str = "preference.json";

pub type RuntimeResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PythonInstall {
    pub id: String,
    pub executable: PathBuf,
    pub label: String,
    pub kind: PythonKind,
    pub version: Option<String>,
    pub major: Option<u8>,
    pub minor: Option<u8>,
    pub arch: Option<String>,
    pub platform: Option<String>,
    pub prefix: Option<PathBuf>,
    pub base_prefix: Option<PathBuf>,
    pub is_venv: bool,
    pub is_conda: bool,
    pub conda_env: Option<String>,
    pub has_pip: bool,
    pub has_venv: bool,
    pub has_ensurepip: bool,
    pub externally_managed: bool,
    pub probe_error: Option<String>,
    pub priority: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum PythonKind {
    Explicit,
    Managed,
    ManagedVenv,
    Portable,
    Conda,
    Path,
}

#[derive(Clone, Debug)]
pub struct RuntimeRootCandidate {
    pub root: PathBuf,
    pub kind: RuntimeRootKind,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RuntimeRootKind {
    Explicit,
    InstallDir,
    AppData,
}

#[derive(Clone, Debug)]
struct PythonSource {
    id_override: Option<String>,
    executable: PathBuf,
    label: String,
    kind: PythonKind,
    priority: i32,
}

impl PythonSource {
    fn id(&self) -> String {
        self.id_override
            .clone()
            .unwrap_or_else(|| python_id(&self.kind, &self.executable))
    }
}

#[derive(Debug, Deserialize)]
struct PythonProbePayload {
    version: Option<String>,
    major: Option<u8>,
    minor: Option<u8>,
    arch: Option<String>,
    platform: Option<String>,
    prefix: Option<String>,
    base_prefix: Option<String>,
    is_venv: Option<bool>,
    is_conda: Option<bool>,
    conda_env: Option<String>,
    has_pip: Option<bool>,
    has_venv: Option<bool>,
    has_ensurepip: Option<bool>,
    externally_managed: Option<bool>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimePreference {
    candidate_id: String,
    python_path: String,
    label: String,
    saved_at_ms: u128,
}

pub fn scan_python_installs<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
) -> Vec<PythonInstall> {
    let mut sources = Vec::new();
    if let Ok(data_dir) = app.path().app_data_dir() {
        if let Some(source) = preferred_python_source(&data_dir) {
            sources.push(source);
        }
    }

    if let Some(path) = env_path("SHINSEKAI_PYTHON") {
        sources.push(PythonSource {
            id_override: None,
            executable: path,
            label: "SHINSEKAI_PYTHON".to_string(),
            kind: PythonKind::Explicit,
            priority: 10_000,
        });
    }

    for root in runtime_root_candidates(app, source_root) {
        if let Some(python) = python_in_prefix(&root.root) {
            sources.push(PythonSource {
                id_override: None,
                executable: python,
                label: format!("managed runtime at {}", root.root.display()),
                kind: match root.kind {
                    RuntimeRootKind::Explicit => PythonKind::Explicit,
                    RuntimeRootKind::InstallDir => PythonKind::Portable,
                    RuntimeRootKind::AppData => PythonKind::Managed,
                },
                priority: match root.kind {
                    RuntimeRootKind::Explicit => 9_000,
                    RuntimeRootKind::AppData => 8_000,
                    RuntimeRootKind::InstallDir => 7_000,
                },
            });
        } else if root.kind == RuntimeRootKind::Explicit {
            sources.push(PythonSource {
                id_override: None,
                executable: root.root,
                label: "SHINSEKAI_RUNTIME_DIR".to_string(),
                kind: PythonKind::Explicit,
                priority: 9_000,
            });
        }
    }

    if let Ok(data_dir) = app.path().app_data_dir() {
        sources.extend(app_data_runtime_sources(&data_dir));
    }
    sources.extend(active_virtual_env_sources());
    sources.extend(conda_python_sources());
    sources.extend(shim_python_sources(source_root));
    sources.extend(path_python_sources());

    dedupe_python_sources(sources)
        .into_iter()
        .map(probe_python_source)
        .collect()
}

pub fn save_runtime_preference<R: Runtime>(
    app: &impl Manager<R>,
    candidate_id: &str,
    python_path: &Path,
    label: &str,
) -> RuntimeResult<()> {
    if !python_path.is_file() {
        return Err(format!("runtime Python does not exist: {}", python_path.display()).into());
    }
    let runtime_home = app.path().app_data_dir()?.join("runtime");
    fs::create_dir_all(&runtime_home)?;
    let saved_at_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    let preference = RuntimePreference {
        candidate_id: candidate_id.to_string(),
        python_path: python_path.display().to_string(),
        label: label.to_string(),
        saved_at_ms,
    };
    fs::write(
        runtime_home.join(RUNTIME_PREFERENCE_FILE),
        serde_json::to_string_pretty(&preference)?,
    )?;
    Ok(())
}

pub fn explicit_python_id(executable: &Path) -> String {
    python_id(&PythonKind::Explicit, executable)
}

pub fn runtime_root_candidates<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
) -> Vec<RuntimeRootCandidate> {
    let mut candidates = Vec::new();
    if let Some(root) = env_path("SHINSEKAI_RUNTIME_DIR") {
        candidates.push(RuntimeRootCandidate {
            root,
            kind: RuntimeRootKind::Explicit,
        });
    }

    if dev_project_root().as_deref() == Some(source_root) {
        candidates.push(RuntimeRootCandidate {
            root: source_root.join("runtime"),
            kind: RuntimeRootKind::InstallDir,
        });
    } else {
        for root in install_runtime_roots(source_root) {
            candidates.push(RuntimeRootCandidate {
                root,
                kind: RuntimeRootKind::InstallDir,
            });
        }
        candidates.push(RuntimeRootCandidate {
            root: source_root.join("runtime"),
            kind: RuntimeRootKind::InstallDir,
        });
    }

    if let Some(exe_dir) = env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf))
    {
        let runtime = exe_dir.join("runtime");
        if runtime != source_root.join("runtime") {
            candidates.push(RuntimeRootCandidate {
                root: runtime,
                kind: RuntimeRootKind::InstallDir,
            });
        }
    }

    if let Ok(data_dir) = app.path().app_data_dir() {
        candidates.push(RuntimeRootCandidate {
            root: data_dir.join("runtime"),
            kind: RuntimeRootKind::AppData,
        });
    }

    dedupe_root_candidates(candidates)
}

pub fn python_in_prefix(prefix: &Path) -> Option<PathBuf> {
    let candidates = [
        prefix.join("bin").join("python3"),
        prefix.join("bin").join("python"),
        prefix.join("Scripts").join("python.exe"),
        prefix.join("Scripts").join("python"),
        prefix.join("python.exe"),
    ];
    candidates.into_iter().find(|candidate| candidate.is_file())
}

fn probe_python_source(source: PythonSource) -> PythonInstall {
    if !source.executable.is_file() {
        let id = source.id();
        return PythonInstall {
            id,
            executable: source.executable,
            label: source.label,
            kind: source.kind,
            version: None,
            major: None,
            minor: None,
            arch: None,
            platform: None,
            prefix: None,
            base_prefix: None,
            is_venv: false,
            is_conda: false,
            conda_env: None,
            has_pip: false,
            has_venv: false,
            has_ensurepip: false,
            externally_managed: false,
            probe_error: Some("python executable not found".to_string()),
            priority: source.priority,
        };
    }

    let output = Command::new(&source.executable)
        .arg("-c")
        .arg(PYTHON_PROBE_SCRIPT)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .output();
    match output {
        Ok(output) if output.status.success() => {
            let payload = serde_json::from_slice::<PythonProbePayload>(&output.stdout);
            match payload {
                Ok(payload) => install_from_payload(source, payload),
                Err(error) => {
                    install_with_error(source, format!("python probe JSON parse failed: {error}"))
                }
            }
        }
        Ok(output) => install_with_error(
            source,
            String::from_utf8_lossy(&output.stderr).trim().to_string(),
        ),
        Err(error) => install_with_error(source, error.to_string()),
    }
}

fn install_from_payload(source: PythonSource, payload: PythonProbePayload) -> PythonInstall {
    let id = source.id();
    PythonInstall {
        id,
        executable: source.executable,
        label: source.label,
        kind: source.kind,
        version: payload.version,
        major: payload.major,
        minor: payload.minor,
        arch: payload.arch,
        platform: payload.platform,
        prefix: payload.prefix.map(PathBuf::from),
        base_prefix: payload.base_prefix.map(PathBuf::from),
        is_venv: payload.is_venv.unwrap_or(false),
        is_conda: payload.is_conda.unwrap_or(false),
        conda_env: payload.conda_env,
        has_pip: payload.has_pip.unwrap_or(false),
        has_venv: payload.has_venv.unwrap_or(false),
        has_ensurepip: payload.has_ensurepip.unwrap_or(false),
        externally_managed: payload.externally_managed.unwrap_or(false),
        probe_error: None,
        priority: source.priority,
    }
}

fn install_with_error(source: PythonSource, error: String) -> PythonInstall {
    let id = source.id();
    PythonInstall {
        id,
        executable: source.executable,
        label: source.label,
        kind: source.kind,
        version: None,
        major: None,
        minor: None,
        arch: None,
        platform: None,
        prefix: None,
        base_prefix: None,
        is_venv: false,
        is_conda: false,
        conda_env: None,
        has_pip: false,
        has_venv: false,
        has_ensurepip: false,
        externally_managed: false,
        probe_error: Some(if error.is_empty() {
            "python probe failed".to_string()
        } else {
            error
        }),
        priority: source.priority,
    }
}

fn python_id(kind: &PythonKind, executable: &Path) -> String {
    let resolved = executable
        .canonicalize()
        .unwrap_or_else(|_| executable.to_path_buf());
    let mut hasher = Sha256::new();
    hasher.update(format!("{kind:?}\0{}", resolved.display()).as_bytes());
    format!("python-{:x}", hasher.finalize())
}

fn conda_python_sources() -> Vec<PythonSource> {
    let mut sources = Vec::new();
    let default_env =
        env::var("SHINSEKAI_CONDA_ENV").unwrap_or_else(|_| DEFAULT_CONDA_ENV.to_string());
    if let Some(prefix) = env_path("CONDA_PREFIX") {
        let active_env = env::var("CONDA_DEFAULT_ENV").unwrap_or_default();
        if let Some(python) = python_in_prefix(&prefix) {
            sources.push(PythonSource {
                id_override: None,
                executable: python,
                label: if active_env.is_empty() {
                    "active conda env".to_string()
                } else {
                    format!("active conda env {active_env}")
                },
                kind: PythonKind::Conda,
                priority: active_conda_priority(&active_env, &default_env),
            });
        }
    }

    if let Some(conda_python) = find_conda_env_python(&default_env) {
        sources.push(PythonSource {
            id_override: None,
            executable: conda_python,
            label: format!("conda/mamba env {default_env}"),
            kind: PythonKind::Conda,
            priority: 6_000,
        });
    }
    sources
}

fn active_conda_priority(active_env: &str, default_env: &str) -> i32 {
    if active_env == default_env {
        6_500
    } else {
        5_700
    }
}

fn active_virtual_env_sources() -> Vec<PythonSource> {
    let mut sources = Vec::new();
    for (variable, label, priority) in [
        ("VIRTUAL_ENV", "active virtualenv", 5_800),
        ("UV_PROJECT_ENVIRONMENT", "uv project environment", 5_700),
    ] {
        if let Some(prefix) = env_path(variable).or_else(|| relative_env_path(variable)) {
            if let Some(python) = python_in_prefix(&prefix) {
                sources.push(PythonSource {
                    id_override: None,
                    executable: python,
                    label: format!("{label} at {}", prefix.display()),
                    kind: PythonKind::Path,
                    priority,
                });
            }
        }
    }
    sources
}

fn app_data_runtime_sources(data_dir: &Path) -> Vec<PythonSource> {
    let runtime_home = data_dir.join("runtime");
    let mut sources = Vec::new();
    if let Some(current_root) = current_runtime_root(&runtime_home) {
        if let Some(python) = python_in_prefix(&current_root) {
            sources.push(PythonSource {
                id_override: None,
                executable: python,
                label: "Shinsekai managed runtime".to_string(),
                kind: PythonKind::Managed,
                priority: 8_000,
            });
        }
    }

    let runtimes_dir = runtime_home.join("runtimes");
    if let Ok(entries) = fs::read_dir(runtimes_dir) {
        for root in entries
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| path.is_dir() && !is_runtime_publish_artifact_dir(path))
        {
            if let Some(python) = python_in_prefix(&root) {
                sources.push(PythonSource {
                    id_override: None,
                    executable: python,
                    label: format!(
                        "Shinsekai managed runtime {}",
                        root.file_name()
                            .and_then(|name| name.to_str())
                            .unwrap_or("runtime")
                    ),
                    kind: PythonKind::Managed,
                    priority: 7_600,
                });
            }
        }
    }

    let venvs_dir = runtime_home.join("venvs");
    if let Ok(entries) = fs::read_dir(venvs_dir) {
        for root in entries
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| path.is_dir() && !is_runtime_publish_artifact_dir(path))
        {
            if let Some(python) = python_in_prefix(&root) {
                sources.push(PythonSource {
                    id_override: None,
                    executable: python,
                    label: format!(
                        "Shinsekai managed venv {}",
                        root.file_name()
                            .and_then(|name| name.to_str())
                            .unwrap_or("venv")
                    ),
                    kind: PythonKind::ManagedVenv,
                    priority: 5_500,
                });
            }
        }
    }
    sources
}

fn is_runtime_publish_artifact_dir(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .map(|name| name.contains(".tmp-") || name.contains(".previous-"))
        .unwrap_or(false)
}

fn preferred_python_source(data_dir: &Path) -> Option<PythonSource> {
    let preference_path = data_dir.join("runtime").join(RUNTIME_PREFERENCE_FILE);
    let text = fs::read_to_string(preference_path).ok()?;
    let preference = serde_json::from_str::<RuntimePreference>(&text).ok()?;
    let executable = PathBuf::from(preference.python_path);
    Some(PythonSource {
        id_override: Some(preference.candidate_id),
        executable,
        label: if preference.label.trim().is_empty() {
            "saved runtime preference".to_string()
        } else {
            preference.label
        },
        kind: PythonKind::Explicit,
        priority: 11_000,
    })
}

fn current_runtime_root(runtime_home: &Path) -> Option<PathBuf> {
    let current_path = runtime_home.join("current.json");
    let text = fs::read_to_string(current_path).ok()?;
    let value = serde_json::from_str::<serde_json::Value>(&text).ok()?;
    if let Some(path) = value.get("path").and_then(|value| value.as_str()) {
        let path = PathBuf::from(path);
        if path.is_absolute() {
            return Some(path);
        }
        return Some(runtime_home.join(path));
    }
    let runtime_id = value
        .get("runtimeId")
        .or_else(|| value.get("runtime_id"))
        .and_then(|value| value.as_str())?;
    Some(runtime_home.join("runtimes").join(runtime_id))
}

fn path_python_sources() -> Vec<PythonSource> {
    let mut sources = Vec::new();
    #[cfg(windows)]
    {
        sources.extend(py_launcher_sources());
    }
    for name in python_candidate_names() {
        if let Some(path) = find_on_path(name) {
            sources.push(PythonSource {
                id_override: None,
                executable: path,
                label: format!("PATH python {name}"),
                kind: PythonKind::Path,
                priority: 1_000,
            });
        }
    }
    sources
}

#[cfg(windows)]
fn py_launcher_sources() -> Vec<PythonSource> {
    let Some(py) = find_on_path("py.exe").or_else(|| find_on_path("py")) else {
        return Vec::new();
    };
    let Ok(output) = Command::new(py).arg("-0p").output() else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(parse_py_launcher_python_path)
        .filter(|path| path.is_file())
        .map(|path| PythonSource {
            id_override: None,
            executable: path,
            label: "Windows py launcher".to_string(),
            kind: PythonKind::Path,
            priority: 1_200,
        })
        .collect()
}

#[cfg(any(windows, test))]
fn parse_py_launcher_python_path(line: &str) -> Option<PathBuf> {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let Some(start) = windows_path_start(trimmed) {
        let path = trimmed[start..].trim().trim_matches('"');
        if !path.is_empty() {
            return Some(PathBuf::from(path));
        }
    }
    trimmed.split_whitespace().last().map(PathBuf::from)
}

#[cfg(any(windows, test))]
fn windows_path_start(value: &str) -> Option<usize> {
    let bytes = value.as_bytes();
    for index in 0..bytes.len().saturating_sub(2) {
        if bytes[index].is_ascii_alphabetic()
            && bytes[index + 1] == b':'
            && matches!(bytes[index + 2], b'\\' | b'/')
        {
            return Some(index);
        }
    }
    value.find(r"\\")
}

fn find_conda_env_python(env_name: &str) -> Option<PathBuf> {
    if let Some(prefix) = env_path("CONDA_PREFIX") {
        if env::var("CONDA_DEFAULT_ENV").ok().as_deref() == Some(env_name) {
            if let Some(python) = python_in_prefix(&prefix) {
                return Some(python);
            }
        }
    }

    conda_like_env_prefixes(env_name)
        .into_iter()
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

fn conda_like_env_prefixes(env_name: &str) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(conda_exe) = env_path("CONDA_EXE").or_else(|| find_on_path("conda")) {
        roots.extend(conda_roots_from_executable(&conda_exe));
    }
    if let Some(mamba_exe) = env_path("MAMBA_EXE").or_else(|| find_on_path("mamba")) {
        roots.extend(conda_roots_from_executable(&mamba_exe));
    }
    if let Some(root) = env_path("MAMBA_ROOT_PREFIX") {
        roots.push(root);
    }
    roots.extend(default_conda_roots());
    roots.extend(default_mamba_roots());

    conda_env_prefixes_from_roots(dedupe_paths(roots), env_name)
}

fn conda_env_prefixes_from_roots(roots: Vec<PathBuf>, env_name: &str) -> Vec<PathBuf> {
    roots
        .into_iter()
        .flat_map(|root| [root.join("envs").join(env_name), root.join(env_name)])
        .collect()
}

fn default_conda_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(home) = home_dir() {
        roots.push(home.join("miniconda3"));
        roots.push(home.join("anaconda3"));
        roots.push(home.join("miniforge3"));
        roots.push(home.join("mambaforge"));
    }
    #[cfg(not(windows))]
    {
        roots.push(PathBuf::from("/opt/miniconda3"));
        roots.push(PathBuf::from("/opt/anaconda3"));
        roots.push(PathBuf::from("/opt/miniforge3"));
        roots.push(PathBuf::from("/opt/mambaforge"));
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

fn default_mamba_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(home) = home_dir() {
        roots.push(home.join(".micromamba"));
        roots.push(home.join("micromamba"));
        roots.push(home.join(".local").join("share").join("mamba"));
    }
    #[cfg(windows)]
    {
        if let Some(local_app_data) = env::var_os("LOCALAPPDATA") {
            roots.push(PathBuf::from(local_app_data).join("mamba"));
        }
    }
    roots
}

fn shim_python_sources(source_root: &Path) -> Vec<PythonSource> {
    let mut sources = Vec::new();
    sources.extend(source_root_virtual_env_sources(source_root));

    if let Some(root) =
        env_path("PYENV_ROOT").or_else(|| home_dir().map(|home| home.join(".pyenv")))
    {
        sources.extend(pyenv_python_sources(&root));
    }
    if let Some(root) =
        env_path("ASDF_DATA_DIR").or_else(|| home_dir().map(|home| home.join(".asdf")))
    {
        sources.extend(asdf_python_sources(&root));
    }
    if let Some(root) = env_path("UV_PYTHON_INSTALL_DIR").or_else(|| {
        home_dir().map(|home| home.join(".local").join("share").join("uv").join("python"))
    }) {
        sources.extend(uv_python_sources(&root));
    }

    sources
}

fn source_root_virtual_env_sources(source_root: &Path) -> Vec<PythonSource> {
    [source_root.join(".venv"), source_root.join("venv")]
        .into_iter()
        .filter_map(|prefix| {
            python_in_prefix(&prefix).map(|python| PythonSource {
                id_override: None,
                executable: python,
                label: format!("project virtualenv at {}", prefix.display()),
                kind: PythonKind::Path,
                priority: 5_600,
            })
        })
        .collect()
}

fn pyenv_python_sources(root: &Path) -> Vec<PythonSource> {
    let mut sources = python_sources_from_shims(root.join("shims"), "pyenv shim", 1_500);
    sources.extend(python_sources_from_install_roots(
        &root.join("versions"),
        "pyenv Python",
        1_450,
    ));
    sources
}

fn asdf_python_sources(root: &Path) -> Vec<PythonSource> {
    let mut sources = python_sources_from_shims(root.join("shims"), "asdf shim", 1_400);
    sources.extend(python_sources_from_install_roots(
        &root.join("installs").join("python"),
        "asdf Python",
        1_350,
    ));
    sources
}

fn uv_python_sources(root: &Path) -> Vec<PythonSource> {
    python_sources_from_install_roots(root, "uv Python", 1_300)
}

fn python_sources_from_shims(shim_dir: PathBuf, label: &str, priority: i32) -> Vec<PythonSource> {
    ["python3", "python", "python.exe", "python3.exe"]
        .into_iter()
        .map(|name| shim_dir.join(name))
        .filter(|path| path.is_file())
        .map(|path| PythonSource {
            id_override: None,
            executable: path,
            label: label.to_string(),
            kind: PythonKind::Path,
            priority,
        })
        .collect()
}

fn python_sources_from_install_roots(root: &Path, label: &str, priority: i32) -> Vec<PythonSource> {
    let Ok(entries) = fs::read_dir(root) else {
        return Vec::new();
    };
    entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .filter_map(|prefix| {
            python_in_prefix(&prefix).map(|python| PythonSource {
                id_override: None,
                executable: python,
                label: format!(
                    "{} {}",
                    label,
                    prefix
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("runtime")
                ),
                kind: PythonKind::Path,
                priority,
            })
        })
        .collect()
}

fn dev_project_root() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent()?.parent().map(Path::to_path_buf)
}

#[cfg(windows)]
fn python_candidate_names() -> &'static [&'static str] {
    &["python.exe", "python3.exe"]
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

fn relative_env_path(variable: &str) -> Option<PathBuf> {
    let raw = env::var_os(variable)?;
    let path = PathBuf::from(raw);
    if path.is_absolute() {
        return Some(path);
    }
    env::current_dir().ok().map(|cwd| cwd.join(path))
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

fn install_runtime_roots(source_root: &Path) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(parent) = source_root.parent() {
        roots.push(parent.join("runtime"));
        if source_root.file_name().and_then(|name| name.to_str()) != Some("resources") {
            if let Some(grandparent) = parent.parent() {
                roots.push(grandparent.join("runtime"));
            }
        }
    }
    roots
}

fn dedupe_root_candidates(candidates: Vec<RuntimeRootCandidate>) -> Vec<RuntimeRootCandidate> {
    let mut deduped: Vec<RuntimeRootCandidate> = Vec::new();
    for candidate in candidates {
        let normalized = candidate
            .root
            .canonicalize()
            .unwrap_or_else(|_| candidate.root.clone());
        if deduped.iter().any(|existing| {
            existing
                .root
                .canonicalize()
                .unwrap_or_else(|_| existing.root.clone())
                == normalized
        }) {
            continue;
        }
        deduped.push(candidate);
    }
    deduped
}

fn dedupe_paths(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut deduped = Vec::new();
    for path in paths {
        let normalized = path.canonicalize().unwrap_or_else(|_| path.clone());
        if deduped.iter().any(|existing: &PathBuf| {
            existing.canonicalize().unwrap_or_else(|_| existing.clone()) == normalized
        }) {
            continue;
        }
        deduped.push(path);
    }
    deduped
}

fn dedupe_python_sources(sources: Vec<PythonSource>) -> Vec<PythonSource> {
    let mut deduped: Vec<PythonSource> = Vec::new();
    for source in sources {
        let normalized = source
            .executable
            .canonicalize()
            .unwrap_or_else(|_| source.executable.clone());
        if let Some(existing) = deduped.iter_mut().find(|existing| {
            existing
                .executable
                .canonicalize()
                .unwrap_or_else(|_| existing.executable.clone())
                == normalized
        }) {
            if source.priority > existing.priority {
                *existing = source;
            }
            continue;
        }
        deduped.push(source);
    }
    deduped
}

#[cfg(test)]
mod tests;

const PYTHON_PROBE_SCRIPT: &str = r#"
import importlib.util
import json
import os
import platform
import sys
import sysconfig
from pathlib import Path

prefix = Path(sys.prefix)
stdlib = Path(sysconfig.get_path("stdlib") or sys.prefix)
externally_managed = (stdlib / "EXTERNALLY-MANAGED").exists() or (prefix / "EXTERNALLY-MANAGED").exists()
payload = {
    "version": platform.python_version(),
    "major": sys.version_info.major,
    "minor": sys.version_info.minor,
    "arch": platform.machine(),
    "platform": sys.platform,
    "prefix": sys.prefix,
    "base_prefix": getattr(sys, "base_prefix", sys.prefix),
    "is_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
    "is_conda": bool(os.environ.get("CONDA_PREFIX")) or (prefix / "conda-meta").is_dir(),
    "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
    "has_pip": importlib.util.find_spec("pip") is not None,
    "has_venv": importlib.util.find_spec("venv") is not None,
    "has_ensurepip": importlib.util.find_spec("ensurepip") is not None,
    "externally_managed": externally_managed,
}
print(json.dumps(payload, ensure_ascii=True))
"#;
