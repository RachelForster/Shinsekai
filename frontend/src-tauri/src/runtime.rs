use std::{
    env,
    error::Error,
    fs::{self, File},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    process::Command,
    time::{Duration, Instant},
};

use flate2::read::GzDecoder;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use tauri::Manager;

type RuntimeResult<T> = Result<T, Box<dyn Error>>;

const MANIFEST_FILE: &str = "runtime_manifest.json";
const DEFAULT_CONDA_ENV: &str = "shinsekai";
const DEFAULT_REQUIRED_MODULES: &[&str] = &["yaml", "pydantic", "requests", "numpy", "pygame"];
const OFFICIAL_PROBE_URL: &str = "https://www.python.org/";
const CHINA_PROBE_URL: &str = "https://mirrors.tuna.tsinghua.edu.cn/";

#[derive(Debug)]
pub struct PythonRuntime {
    pub command: Command,
    pub description: String,
}

#[derive(Clone, Debug)]
struct RuntimeCandidate {
    root: PathBuf,
    kind: RuntimeCandidateKind,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RuntimeCandidateKind {
    Explicit,
    InstallDir,
    AppData,
}

#[derive(Clone, Debug, Deserialize)]
struct RuntimeManifest {
    version: String,
    #[serde(default)]
    required_modules: Vec<String>,
    #[serde(default)]
    probes: ProbeConfig,
    targets: Vec<RuntimeTarget>,
}

#[derive(Clone, Debug, Default, Deserialize)]
struct ProbeConfig {
    #[serde(default)]
    official: Vec<String>,
    #[serde(default)]
    china: Vec<String>,
}

#[derive(Clone, Debug, Deserialize)]
struct RuntimeTarget {
    platform: String,
    arch: String,
    archive_type: ArchiveType,
    sha256: String,
    #[serde(default)]
    official_url: Option<String>,
    #[serde(default)]
    china_url: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "kebab-case")]
enum ArchiveType {
    TarGz,
    Zip,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum NetworkRegion {
    China,
    Official,
}

#[derive(Clone, Copy, Debug, Default)]
struct ProbeStats {
    successes: usize,
    best_latency: Option<Duration>,
}

pub fn resolve_python_runtime(
    app: &tauri::App,
    source_root: &Path,
) -> RuntimeResult<PythonRuntime> {
    let manifest = load_manifest(source_root).ok();
    let required_modules = required_modules_from_env(manifest.as_ref());

    if let Some(raw) = env::var_os("SHINSEKAI_PYTHON") {
        let path = PathBuf::from(raw);
        if validate_python(&path, source_root, required_modules.as_deref()) {
            return Ok(PythonRuntime {
                command: Command::new(path),
                description: "SHINSEKAI_PYTHON".to_string(),
            });
        }
    }

    for candidate in runtime_candidates(app, source_root) {
        if let Some(python) = python_in_prefix(&candidate.root) {
            if validate_python(&python, source_root, required_modules.as_deref()) {
                return Ok(PythonRuntime {
                    command: Command::new(python),
                    description: format!("managed runtime at {}", candidate.root.display()),
                });
            }
        }
    }

    let conda_env =
        env::var("SHINSEKAI_CONDA_ENV").unwrap_or_else(|_| DEFAULT_CONDA_ENV.to_string());
    if let Some(conda_python) = find_conda_env_python(&conda_env) {
        if validate_python(&conda_python, source_root, required_modules.as_deref()) {
            return Ok(PythonRuntime {
                command: Command::new(conda_python),
                description: format!("conda env {conda_env}"),
            });
        }
    }

    for name in python_candidate_names() {
        if let Some(path) = find_on_path(name) {
            if validate_python(&path, source_root, required_modules.as_deref()) {
                return Ok(PythonRuntime {
                    command: Command::new(path),
                    description: format!("PATH python {name}"),
                });
            }
        }
    }

    if let Some(manifest) = manifest.as_ref() {
        match repair_runtime(app, source_root, manifest) {
            Ok(Some(runtime_root)) => {
                if let Some(python) = python_in_prefix(&runtime_root) {
                    if validate_python(&python, source_root, required_modules.as_deref()) {
                        return Ok(PythonRuntime {
                            command: Command::new(python),
                            description: format!("repaired runtime at {}", runtime_root.display()),
                        });
                    }
                }
            }
            Ok(None) => {}
            Err(error) => {
                return Err(format!(
                    "no complete Python runtime found and runtime repair failed: {error}"
                )
                .into());
            }
        }
    }

    Err("no complete Python runtime found; set SHINSEKAI_PYTHON, provide runtime/, install the shinsekai conda env, or configure runtime_manifest.json".into())
}

fn runtime_candidates(app: &tauri::App, source_root: &Path) -> Vec<RuntimeCandidate> {
    let mut candidates = Vec::new();
    if let Some(root) = env_path("SHINSEKAI_RUNTIME_DIR") {
        candidates.push(RuntimeCandidate {
            root,
            kind: RuntimeCandidateKind::Explicit,
        });
    }

    if dev_project_root().as_deref() == Some(source_root) {
        candidates.push(RuntimeCandidate {
            root: source_root.join("runtime"),
            kind: RuntimeCandidateKind::InstallDir,
        });
    } else {
        for root in install_runtime_roots(source_root) {
            candidates.push(RuntimeCandidate {
                root,
                kind: RuntimeCandidateKind::InstallDir,
            });
        }
        candidates.push(RuntimeCandidate {
            root: source_root.join("runtime"),
            kind: RuntimeCandidateKind::InstallDir,
        });
    }

    if let Some(exe_dir) = env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf))
    {
        let runtime = exe_dir.join("runtime");
        if runtime != source_root.join("runtime") {
            candidates.push(RuntimeCandidate {
                root: runtime,
                kind: RuntimeCandidateKind::InstallDir,
            });
        }
    }

    if let Ok(data_dir) = app.path().app_data_dir() {
        candidates.push(RuntimeCandidate {
            root: data_dir.join("runtime"),
            kind: RuntimeCandidateKind::AppData,
        });
    }

    dedupe_candidates(candidates)
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

fn dedupe_candidates(candidates: Vec<RuntimeCandidate>) -> Vec<RuntimeCandidate> {
    let mut deduped: Vec<RuntimeCandidate> = Vec::new();
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

fn repair_runtime(
    app: &tauri::App,
    source_root: &Path,
    manifest: &RuntimeManifest,
) -> RuntimeResult<Option<PathBuf>> {
    let Some(target) = manifest_target(manifest) else {
        return Ok(None);
    };

    let Some(url) = choose_runtime_url(manifest, target) else {
        return Ok(None);
    };

    let Some(candidate) = runtime_candidates(app, source_root)
        .into_iter()
        .find(|candidate| {
            candidate.kind == RuntimeCandidateKind::Explicit
                || can_write_runtime_parent(&candidate.root)
        })
    else {
        return Ok(None);
    };

    download_and_extract_runtime(&url, target, manifest, &candidate.root)?;
    Ok(Some(candidate.root))
}

fn load_manifest(source_root: &Path) -> RuntimeResult<RuntimeManifest> {
    let path =
        env_path("SHINSEKAI_RUNTIME_MANIFEST").unwrap_or_else(|| source_root.join(MANIFEST_FILE));
    let text = fs::read_to_string(&path)?;
    Ok(serde_json::from_str(&text)?)
}

fn required_modules_from_env(manifest: Option<&RuntimeManifest>) -> Option<Vec<String>> {
    if let Ok(raw) = env::var("SHINSEKAI_RUNTIME_REQUIRED_MODULES") {
        let modules = raw
            .split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        if !modules.is_empty() {
            return Some(modules);
        }
    }

    if let Some(manifest) = manifest {
        if !manifest.required_modules.is_empty() {
            return Some(manifest.required_modules.clone());
        }
    }

    Some(
        DEFAULT_REQUIRED_MODULES
            .iter()
            .map(|module| (*module).to_string())
            .collect(),
    )
}

fn validate_python(python: &Path, source_root: &Path, required_modules: Option<&[String]>) -> bool {
    if !python.is_file() {
        return false;
    }

    let mut script = String::from("import sys\n");
    script.push_str("assert sys.version_info >= (3, 10)\n");
    if let Some(modules) = required_modules {
        for module in modules {
            script.push_str("import ");
            script.push_str(module);
            script.push('\n');
        }
    }

    Command::new(python)
        .arg("-c")
        .arg(script)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
        && validate_bridge_runtime(python, source_root)
}

fn validate_bridge_runtime(python: &Path, source_root: &Path) -> bool {
    let bridge = source_root.join("frontend_bridge.py");
    let requirements = source_root.join("requirements.txt");
    if !bridge.is_file() || !requirements.is_file() {
        return false;
    }

    Command::new(python)
        .arg(&bridge)
        .arg("--check-runtime")
        .arg("--project-root")
        .arg(source_root)
        .arg("--requirements-file")
        .arg(&requirements)
        .current_dir(source_root)
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn manifest_target(manifest: &RuntimeManifest) -> Option<&RuntimeTarget> {
    let platform = current_platform();
    let arch = current_arch();
    manifest
        .targets
        .iter()
        .find(|target| target.platform == platform && target.arch == arch)
}

fn choose_runtime_url(manifest: &RuntimeManifest, target: &RuntimeTarget) -> Option<String> {
    let region = detect_network_region(manifest);
    match region {
        NetworkRegion::China => target
            .china_url
            .clone()
            .or_else(|| target.official_url.clone()),
        NetworkRegion::Official => target
            .official_url
            .clone()
            .or_else(|| target.china_url.clone()),
    }
}

fn detect_network_region(manifest: &RuntimeManifest) -> NetworkRegion {
    let china_probes = if manifest.probes.china.is_empty() {
        vec![CHINA_PROBE_URL.to_string()]
    } else {
        manifest.probes.china.clone()
    };
    let official_probes = if manifest.probes.official.is_empty() {
        vec![OFFICIAL_PROBE_URL.to_string()]
    } else {
        manifest.probes.official.clone()
    };

    let china_stats = probe_urls(&china_probes);
    let official_stats = probe_urls(&official_probes);
    if china_stats.successes > 0 && official_stats.successes == 0 {
        return NetworkRegion::China;
    }
    if china_stats.successes > official_stats.successes {
        return NetworkRegion::China;
    }
    if china_stats.successes == official_stats.successes {
        if let (Some(china_latency), Some(official_latency)) =
            (china_stats.best_latency, official_stats.best_latency)
        {
            if china_latency < official_latency {
                return NetworkRegion::China;
            }
        }
    }
    NetworkRegion::Official
}

fn probe_urls(urls: &[String]) -> ProbeStats {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(3))
        .build();
    let Ok(client) = client else {
        return ProbeStats::default();
    };
    let mut stats = ProbeStats::default();
    for url in urls {
        let started = Instant::now();
        let ok = client
            .head(url.as_str())
            .send()
            .or_else(|_| client.get(url.as_str()).send())
            .map(|response| response.status().is_success() || response.status().is_redirection())
            .unwrap_or(false);
        if ok {
            let latency = started.elapsed();
            stats.successes += 1;
            stats.best_latency = Some(
                stats
                    .best_latency
                    .map(|current| current.min(latency))
                    .unwrap_or(latency),
            );
        }
    }
    stats
}

fn download_and_extract_runtime(
    url: &str,
    target: &RuntimeTarget,
    manifest: &RuntimeManifest,
    runtime_root: &Path,
) -> RuntimeResult<()> {
    let parent = runtime_root.parent().ok_or("runtime path has no parent")?;
    fs::create_dir_all(parent)?;
    let archive_path = parent.join("shinsekai-runtime.download");
    let staging_root = parent.join("runtime.tmp");

    let mut response = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(1800))
        .build()?
        .get(url)
        .send()?
        .error_for_status()?;

    let mut archive = File::create(&archive_path)?;
    io::copy(&mut response, &mut archive)?;
    drop(archive);

    verify_sha256(&archive_path, &target.sha256)?;

    if staging_root.exists() {
        fs::remove_dir_all(&staging_root)?;
    }
    fs::create_dir_all(&staging_root)?;

    match target.archive_type {
        ArchiveType::TarGz => extract_tar_gz(&archive_path, &staging_root)?,
        ArchiveType::Zip => extract_zip(&archive_path, &staging_root)?,
    }

    let runtime_payload = normalize_extracted_runtime(&staging_root);
    write_runtime_marker(&runtime_payload, manifest)?;

    if runtime_root.exists() {
        fs::remove_dir_all(runtime_root)?;
    }
    fs::rename(&runtime_payload, runtime_root)?;

    let _ = fs::remove_file(&archive_path);
    if staging_root.exists() {
        let _ = fs::remove_dir_all(&staging_root);
    }
    Ok(())
}

fn verify_sha256(path: &Path, expected: &str) -> RuntimeResult<()> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 128 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let actual = format!("{:x}", hasher.finalize());
    if actual.eq_ignore_ascii_case(expected) {
        return Ok(());
    }
    Err(format!("runtime archive sha256 mismatch: expected {expected}, got {actual}").into())
}

fn extract_tar_gz(archive_path: &Path, destination: &Path) -> RuntimeResult<()> {
    let archive = File::open(archive_path)?;
    let decoder = GzDecoder::new(archive);
    let mut archive = tar::Archive::new(decoder);
    archive.unpack(destination)?;
    Ok(())
}

fn extract_zip(archive_path: &Path, destination: &Path) -> RuntimeResult<()> {
    let archive = File::open(archive_path)?;
    let mut archive = zip::ZipArchive::new(archive)?;
    archive.extract(destination)?;
    Ok(())
}

fn normalize_extracted_runtime(staging_root: &Path) -> PathBuf {
    if python_in_prefix(staging_root).is_some() {
        return staging_root.to_path_buf();
    }
    let Ok(entries) = fs::read_dir(staging_root) else {
        return staging_root.to_path_buf();
    };
    let dirs = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .collect::<Vec<_>>();
    if dirs.len() == 1 && python_in_prefix(&dirs[0]).is_some() {
        return dirs[0].clone();
    }
    staging_root.to_path_buf()
}

fn write_runtime_marker(runtime_root: &Path, manifest: &RuntimeManifest) -> RuntimeResult<()> {
    let marker = runtime_root.join(".shinsekai-runtime.json");
    let text = serde_json::json!({
        "version": manifest.version,
        "platform": current_platform(),
        "arch": current_arch()
    })
    .to_string();
    fs::write(marker, text)?;
    Ok(())
}

fn can_write_runtime_parent(runtime_root: &Path) -> bool {
    let Some(parent) = runtime_root.parent() else {
        return false;
    };
    if fs::create_dir_all(parent).is_err() {
        return false;
    }
    let probe = parent.join(".shinsekai-runtime-write-test");
    match File::create(&probe).and_then(|mut file| file.write_all(b"ok")) {
        Ok(()) => {
            let _ = fs::remove_file(probe);
            true
        }
        Err(_) => false,
    }
}

fn python_in_prefix(prefix: &Path) -> Option<PathBuf> {
    let candidates = [
        prefix.join("bin").join("python3"),
        prefix.join("bin").join("python"),
        prefix.join("python.exe"),
    ];
    candidates.into_iter().find(|candidate| candidate.is_file())
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

fn dev_project_root() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent()?.parent().map(Path::to_path_buf)
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

fn env_path(name: &str) -> Option<PathBuf> {
    env::var_os(name)
        .map(PathBuf::from)
        .map(expand_home)
        .map(|path| path.canonicalize().unwrap_or(path))
}

fn expand_home(path: PathBuf) -> PathBuf {
    let raw = path.as_os_str().to_string_lossy();
    if raw == "~" {
        return home_dir().unwrap_or(path);
    }
    if let Some(rest) = raw.strip_prefix("~/") {
        if let Some(home) = home_dir() {
            return home.join(rest);
        }
    }
    path
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

fn current_platform() -> &'static str {
    #[cfg(target_os = "windows")]
    {
        "windows"
    }
    #[cfg(target_os = "macos")]
    {
        "macos"
    }
    #[cfg(target_os = "linux")]
    {
        "linux"
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
    {
        "unknown"
    }
}

fn current_arch() -> &'static str {
    #[cfg(target_arch = "x86_64")]
    {
        "x64"
    }
    #[cfg(target_arch = "aarch64")]
    {
        "arm64"
    }
    #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
    {
        "unknown"
    }
}
