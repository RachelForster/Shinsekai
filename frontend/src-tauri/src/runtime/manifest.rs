use std::{
    collections::HashMap,
    env,
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use serde::Deserialize;

pub type RuntimeResult<T> = Result<T, Box<dyn Error>>;

pub const DEFAULT_PROFILE: &str = "desktop-core";
pub const MANIFEST_FILE: &str = "runtime_manifest.json";
const DEFAULT_REQUIRED_IMPORTS: &[&str] = &["yaml", "pydantic", "requests", "numpy", "pygame"];
const DEFAULT_REQUIREMENTS_FILE: &str = "requirements-runtime-core.txt";
const FALLBACK_REQUIREMENTS_FILE: &str = "requirements.txt";
const OFFICIAL_PROBE_URL: &str = "https://www.python.org/";
const CHINA_PROBE_URL: &str = "https://mirrors.tuna.tsinghua.edu.cn/";
const OFFICIAL_PIP_INDEX_URL: &str = "https://pypi.org/simple/";
const CHINA_PIP_INDEX_URL: &str = "https://pypi.tuna.tsinghua.edu.cn/simple/";
const CHINA_PIP_INDEX_URLS: &[&str] = &[
    "https://pypi.tuna.tsinghua.edu.cn/simple/",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://mirrors.ustc.edu.cn/pypi/simple/",
    "https://mirrors.hit.edu.cn/pypi/web/simple/",
];

#[derive(Clone, Debug, Default)]
pub struct RuntimeRequirements {
    pub imports: Vec<String>,
    pub python: Option<String>,
    pub requirements_file: String,
    pub bridge_check: bool,
}

#[derive(Clone, Debug, Deserialize)]
pub struct RuntimeManifest {
    #[allow(dead_code)]
    pub version: String,
    #[serde(default)]
    #[allow(dead_code)]
    pub schema: Option<u32>,
    #[serde(default)]
    pub required_modules: Vec<String>,
    #[serde(default)]
    pub profiles: HashMap<String, RuntimeProfile>,
    #[serde(default)]
    pub probes: ProbeConfig,
    #[serde(default)]
    pub pip_indexes: PipIndexConfig,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct RuntimeProfile {
    #[serde(default)]
    pub extends: Option<String>,
    #[serde(default, rename = "python")]
    pub python: Option<String>,
    #[serde(default)]
    pub imports: Vec<String>,
    #[serde(default)]
    pub requirements: Option<String>,
    #[serde(default)]
    pub bridge_check: Option<bool>,
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct ProbeConfig {
    #[serde(default)]
    pub official: Vec<String>,
    #[serde(default)]
    pub china: Vec<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PipIndexConfig {
    #[serde(default = "default_official_pip_index")]
    pub official: Option<String>,
    #[serde(default)]
    pub official_urls: Vec<String>,
    #[serde(default = "default_china_pip_index")]
    pub china: Option<String>,
    #[serde(default = "default_china_pip_indexes")]
    pub china_urls: Vec<String>,
}

impl Default for PipIndexConfig {
    fn default() -> Self {
        Self {
            official: default_official_pip_index(),
            official_urls: Vec::new(),
            china: default_china_pip_index(),
            china_urls: default_china_pip_indexes(),
        }
    }
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

pub fn load_manifest(source_root: &Path) -> RuntimeResult<RuntimeManifest> {
    let path =
        env_path("SHINSEKAI_RUNTIME_MANIFEST").unwrap_or_else(|| source_root.join(MANIFEST_FILE));
    let text = fs::read_to_string(&path)?;
    Ok(serde_json::from_str(&text)?)
}

pub fn runtime_requirements(
    source_root: &Path,
    manifest: Option<&RuntimeManifest>,
    profile: &str,
) -> RuntimeRequirements {
    let mut requirements = manifest
        .map(|manifest| requirements_from_profile(manifest, profile))
        .unwrap_or_else(default_runtime_requirements);

    if let Some(imports) = imports_from_env() {
        requirements.imports = imports;
    } else if requirements.imports.is_empty() {
        requirements.imports = manifest
            .filter(|manifest| !manifest.required_modules.is_empty())
            .map(|manifest| manifest.required_modules.clone())
            .unwrap_or_else(default_required_imports);
    }

    requirements.requirements_file =
        runtime_requirements_file(source_root, Some(&requirements.requirements_file));
    requirements
}

fn default_runtime_requirements() -> RuntimeRequirements {
    RuntimeRequirements {
        imports: Vec::new(),
        python: None,
        requirements_file: DEFAULT_REQUIREMENTS_FILE.to_string(),
        bridge_check: true,
    }
}

fn default_required_imports() -> Vec<String> {
    DEFAULT_REQUIRED_IMPORTS
        .iter()
        .map(|module| (*module).to_string())
        .collect()
}

fn imports_from_env() -> Option<Vec<String>> {
    let raw = env::var("SHINSEKAI_RUNTIME_REQUIRED_MODULES").ok()?;
    let modules = raw
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    if modules.is_empty() {
        None
    } else {
        Some(modules)
    }
}

fn requirements_from_profile(
    manifest: &RuntimeManifest,
    profile_name: &str,
) -> RuntimeRequirements {
    let mut stack = Vec::new();
    let mut seen_names = Vec::new();
    let mut current = Some(profile_name.to_string());
    while let Some(name) = current {
        if seen_names.iter().any(|seen| seen == &name) {
            break;
        }
        let Some(profile) = manifest.profiles.get(&name) else {
            break;
        };
        current = profile.extends.clone();
        seen_names.push(name);
        stack.push(profile.clone());
    }
    stack.reverse();

    let mut result = RuntimeRequirements {
        requirements_file: DEFAULT_REQUIREMENTS_FILE.to_string(),
        bridge_check: true,
        python: None,
        ..RuntimeRequirements::default()
    };
    for profile in stack {
        if !profile.imports.is_empty() {
            result.imports = profile.imports;
        }
        if let Some(requirements) = profile.requirements {
            result.requirements_file = requirements;
        }
        if let Some(python) = profile.python {
            result.python = Some(python);
        }
        if let Some(bridge_check) = profile.bridge_check {
            result.bridge_check = bridge_check;
        }
    }
    result
}

fn runtime_requirements_file(source_root: &Path, manifest_value: Option<&str>) -> String {
    if let Ok(raw) = env::var("SHINSEKAI_RUNTIME_REQUIREMENTS_FILE") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            return trimmed.to_string();
        }
    }
    if let Some(value) = manifest_value {
        if !value.trim().is_empty() {
            return value.to_string();
        }
    }
    if source_root.join(DEFAULT_REQUIREMENTS_FILE).is_file() {
        DEFAULT_REQUIREMENTS_FILE.to_string()
    } else {
        FALLBACK_REQUIREMENTS_FILE.to_string()
    }
}

pub fn pip_index_urls_for_source(manifest: &RuntimeManifest, source: Option<&str>) -> Vec<String> {
    let pip_configured =
        env::var_os("PIP_INDEX_URL").is_some() || env::var_os("PIP_CONFIG_FILE").is_some();
    let custom_index = env::var("SHINSEKAI_PIP_INDEX_URL").ok();
    let custom_indexes = env::var("SHINSEKAI_PIP_INDEX_URLS").ok();
    let runtime_source = env::var("SHINSEKAI_RUNTIME_SOURCE").ok();
    pip_index_urls_for_source_values(
        manifest,
        source,
        pip_configured,
        custom_index.as_deref(),
        custom_indexes.as_deref(),
        runtime_source.as_deref(),
    )
}

fn pip_index_urls_for_source_values(
    manifest: &RuntimeManifest,
    source: Option<&str>,
    pip_configured: bool,
    custom_index: Option<&str>,
    custom_indexes: Option<&str>,
    runtime_source: Option<&str>,
) -> Vec<String> {
    if pip_configured {
        return Vec::new();
    }
    let custom_urls = configured_pip_indexes(custom_index, custom_indexes);
    if !custom_urls.is_empty() {
        return custom_urls;
    }

    match normalized_source(source).as_deref() {
        Some("china") => return china_pip_indexes(manifest),
        Some("official") => return official_pip_indexes(manifest),
        Some(source) if source == "auto" || source.is_empty() => {}
        Some(_) => {}
        None => {}
    }
    if let Some(env_source) = runtime_source {
        match normalized_source(Some(&env_source)).as_deref() {
            Some("china") => return china_pip_indexes(manifest),
            Some("official") => return official_pip_indexes(manifest),
            _ => {}
        }
    }

    let official = official_pip_indexes(manifest);
    let china = china_pip_indexes(manifest);
    match (official.is_empty(), china.is_empty()) {
        (false, true) => official,
        (true, false) => china,
        (true, true) => Vec::new(),
        (false, false) => match detect_network_region(manifest) {
            NetworkRegion::China => ordered_pip_indexes(&china, &official),
            NetworkRegion::Official => ordered_pip_indexes(&official, &china),
        },
    }
}

fn normalized_source(source: Option<&str>) -> Option<String> {
    source.map(|value| value.trim().to_ascii_lowercase())
}

fn official_pip_indexes(manifest: &RuntimeManifest) -> Vec<String> {
    source_pip_indexes(
        manifest.pip_indexes.official.as_deref(),
        &manifest.pip_indexes.official_urls,
    )
}

fn china_pip_indexes(manifest: &RuntimeManifest) -> Vec<String> {
    source_pip_indexes(
        manifest.pip_indexes.china.as_deref(),
        &manifest.pip_indexes.china_urls,
    )
}

fn source_pip_indexes(single_index: Option<&str>, index_urls: &[String]) -> Vec<String> {
    let mut urls = Vec::new();
    push_pip_index(&mut urls, single_index);
    for url in index_urls {
        push_pip_index(&mut urls, Some(url));
    }
    urls
}

fn configured_pip_indexes(single_index: Option<&str>, index_urls: Option<&str>) -> Vec<String> {
    let mut urls = Vec::new();
    push_pip_index(&mut urls, single_index);
    if let Some(raw) = index_urls {
        for line in raw.lines() {
            for url in line.split(',') {
                push_pip_index(&mut urls, Some(url));
            }
        }
    }
    urls
}

fn ordered_pip_indexes(primary: &[String], fallback: &[String]) -> Vec<String> {
    let mut urls = Vec::new();
    for url in primary {
        push_pip_index(&mut urls, Some(url));
    }
    for url in fallback {
        push_pip_index(&mut urls, Some(url));
    }
    urls
}

fn push_pip_index(urls: &mut Vec<String>, url: Option<&str>) {
    let Some(url) = url.map(str::trim).filter(|value| !value.is_empty()) else {
        return;
    };
    if !urls.iter().any(|existing| existing == url) {
        urls.push(url.to_string());
    }
}

fn default_official_pip_index() -> Option<String> {
    Some(OFFICIAL_PIP_INDEX_URL.to_string())
}

fn default_china_pip_index() -> Option<String> {
    Some(CHINA_PIP_INDEX_URL.to_string())
}

fn default_china_pip_indexes() -> Vec<String> {
    CHINA_PIP_INDEX_URLS
        .iter()
        .map(|url| (*url).to_string())
        .collect()
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

pub fn current_platform() -> &'static str {
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

pub fn current_arch() -> &'static str {
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

pub fn env_path(name: &str) -> Option<PathBuf> {
    env::var_os(name)
        .map(PathBuf::from)
        .map(expand_home)
        .map(|path| path.canonicalize().unwrap_or(path))
}

pub fn expand_home(path: PathBuf) -> PathBuf {
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

pub fn home_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        env::var_os("USERPROFILE").map(PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        env::var_os("HOME").map(PathBuf::from)
    }
}

#[cfg(test)]
mod tests;
