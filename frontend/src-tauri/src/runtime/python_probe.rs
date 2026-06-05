use std::{
    path::{Path, PathBuf},
    process::Command,
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{Manager, Runtime};

use super::python_env;

pub const INSTALL_DIR_RUNTIME_ID: &str = "install-dir-runtime";
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
}

#[derive(Clone, Debug)]
pub struct RuntimeRootCandidate {
    pub root: PathBuf,
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
    let sources = managed_python_sources(runtime_root_candidates(app, source_root));
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
    _app: &impl Manager<R>,
    source_root: &Path,
) -> Vec<RuntimeRootCandidate> {
    vec![RuntimeRootCandidate {
        root: install_dir_runtime_root(source_root),
    }]
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

    let mut command = Command::new(&source.executable);
    command.arg("-c").arg(PYTHON_PROBE_SCRIPT);
    python_env::configure_python_command(&mut command, &source.executable);
    let output = command.output();
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

fn managed_python_sources(runtime_roots: Vec<RuntimeRootCandidate>) -> Vec<PythonSource> {
    let mut sources = Vec::new();
    for root in runtime_roots {
        if let Some(python) = python_in_prefix(&root.root) {
            sources.push(PythonSource {
                id_override: Some(INSTALL_DIR_RUNTIME_ID.to_string()),
                executable: python,
                label: format!("Shinsekai bundled runtime @ {}", display_path(&root.root)),
                kind: PythonKind::Managed,
                priority: PRIORITY_INSTALL_DIR_RUNTIME,
            });
        }
    }
    sources
}

pub fn install_dir_runtime_root(source_root: &Path) -> PathBuf {
    source_root.join("runtime")
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
