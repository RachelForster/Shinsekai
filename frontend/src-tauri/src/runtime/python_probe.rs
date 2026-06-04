use std::{
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{Manager, Runtime};

use super::manifest::env_path;

const PRIORITY_INSTALL_DIR_RUNTIME: i32 = 9_000;

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
    Managed,
    ManagedVenv,
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

pub fn scan_python_installs<R: Runtime>(
    app: &impl Manager<R>,
    source_root: &Path,
) -> Vec<PythonInstall> {
    let data_dir = app.path().app_data_dir().ok();
    let sources = managed_python_sources(
        runtime_root_candidates(app, source_root),
        data_dir.as_deref(),
    );
    dedupe_python_sources(sources)
        .into_iter()
        .map(probe_python_source)
        .collect()
}

pub fn display_path(path: &Path) -> String {
    display_path_text(&path.as_os_str().to_string_lossy())
}

pub fn display_path_text(value: &str) -> String {
    let trimmed = value.trim();
    if let Some(rest) = strip_case_insensitive_prefix(trimmed, r"\\?\UNC\") {
        return format!(r"\\{rest}");
    }
    if let Some(rest) = strip_case_insensitive_prefix(trimmed, "//?/UNC/") {
        return format!("//{rest}");
    }
    for prefix in [r"\\?\", r"\\.\"].iter() {
        if let Some(rest) = strip_case_insensitive_prefix(trimmed, prefix) {
            return rest.to_string();
        }
    }
    for prefix in ["//?/", "//./"].iter() {
        if let Some(rest) = strip_case_insensitive_prefix(trimmed, prefix) {
            return rest.to_string();
        }
    }
    trimmed.to_string()
}

fn strip_case_insensitive_prefix<'a>(value: &'a str, prefix: &str) -> Option<&'a str> {
    value
        .get(..prefix.len())
        .filter(|head| head.eq_ignore_ascii_case(prefix))
        .and_then(|_| value.get(prefix.len()..))
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
        prefix.join("bin").join("python3.13"),
        prefix.join("bin").join("python3.12"),
        prefix.join("bin").join("python3.11"),
        prefix.join("bin").join("python3.10"),
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

fn managed_python_sources(
    runtime_roots: Vec<RuntimeRootCandidate>,
    data_dir: Option<&Path>,
) -> Vec<PythonSource> {
    let mut sources = Vec::new();
    for root in runtime_roots {
        if let Some(python) = python_in_prefix(&root.root) {
            sources.push(PythonSource {
                id_override: None,
                executable: python,
                label: match root.kind {
                    RuntimeRootKind::Explicit => {
                        format!("SHINSEKAI_RUNTIME_DIR at {}", display_path(&root.root))
                    }
                    RuntimeRootKind::InstallDir => {
                        format!("Shinsekai bundled runtime at {}", display_path(&root.root))
                    }
                    RuntimeRootKind::AppData => {
                        format!("Shinsekai managed runtime at {}", display_path(&root.root))
                    }
                },
                kind: PythonKind::Managed,
                priority: match root.kind {
                    RuntimeRootKind::Explicit => 10_000,
                    RuntimeRootKind::InstallDir => PRIORITY_INSTALL_DIR_RUNTIME,
                    RuntimeRootKind::AppData => 8_000,
                },
            });
        } else if root.kind == RuntimeRootKind::Explicit {
            sources.push(PythonSource {
                id_override: None,
                executable: root.root,
                label: "SHINSEKAI_RUNTIME_DIR".to_string(),
                kind: PythonKind::Managed,
                priority: 10_000,
            });
        }
    }

    if let Some(data_dir) = data_dir {
        sources.extend(app_data_runtime_sources(data_dir));
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

fn dev_project_root() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent()?.parent().map(Path::to_path_buf)
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
