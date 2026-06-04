use std::{path::Path, process::Command};

use serde::{Deserialize, Serialize};

use super::{
    manifest::{current_arch, runtime_requirements, RuntimeManifest},
    python_env,
    python_probe::{scan_python_installs, PythonInstall, PythonKind},
};

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeScanView {
    pub selected_candidate_id: Option<String>,
    pub recommended_action: Option<RuntimeRepairActionKind>,
    pub candidates: Vec<RuntimeCandidateView>,
    pub message: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeCandidateView {
    pub id: String,
    pub python_id: Option<String>,
    pub label: String,
    pub path: String,
    pub display_path: String,
    pub kind: RuntimeKind,
    pub version: Option<String>,
    pub status: RuntimeCandidateStatus,
    pub message: Option<String>,
    pub score: i32,
    pub selected: bool,
    pub managed: bool,
    pub missing_packages: Vec<String>,
    pub missing_imports: Vec<String>,
    pub python_version: Option<String>,
    pub warnings: Vec<String>,
    pub repair_actions: Vec<RuntimeRepairActionKind>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum RuntimeKind {
    Explicit,
    Managed,
    ManagedVenv,
    Portable,
    Conda,
    Path,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(dead_code)]
pub enum RuntimeCandidateStatus {
    Ready,
    MissingCoreDeps,
    MissingOptionalDeps,
    UnsupportedVersion,
    WrongArchitecture,
    BrokenBridge,
    BrokenPython,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum RuntimeRepairActionKind {
    Start,
    CreateManagedVenv,
    InstallRuntimeDeps,
    SelectDifferentRuntime,
}

#[derive(Debug)]
#[allow(dead_code)]
struct RuntimeCheckReport {
    ok: bool,
    python_ok: bool,
    bridge_ok: bool,
    missing_imports: Vec<String>,
    missing_distributions: Vec<String>,
    stderr: String,
    stdout: String,
    message: String,
}

pub fn scan_runtime_candidates<R: tauri::Runtime>(
    app: &impl tauri::Manager<R>,
    source_root: &Path,
    manifest: Option<&RuntimeManifest>,
    profile: &str,
) -> RuntimeScanView {
    let requirements = runtime_requirements(source_root, manifest, profile);
    let installs = scan_python_installs(app, source_root);
    let mut candidates = installs
        .iter()
        .map(|install| resolve_python_install(install, source_root, profile, &requirements))
        .collect::<Vec<_>>();

    candidates.sort_by(|left, right| {
        right
            .score
            .cmp(&left.score)
            .then_with(|| left.label.cmp(&right.label))
    });
    let selected_candidate_id = candidates
        .iter()
        .find(|candidate| candidate.status == RuntimeCandidateStatus::Ready)
        .map(|candidate| candidate.id.clone());
    for candidate in &mut candidates {
        candidate.selected = Some(&candidate.id) == selected_candidate_id.as_ref();
    }

    let recommended_action = recommended_action(&candidates, selected_candidate_id.as_deref());
    let message = scan_message(&candidates, selected_candidate_id.as_deref());
    RuntimeScanView {
        selected_candidate_id,
        recommended_action,
        candidates,
        message,
    }
}

pub fn ready_candidate<'a>(
    view: &'a RuntimeScanView,
    requested_candidate_id: Option<&str>,
) -> Option<&'a RuntimeCandidateView> {
    if let Some(id) = requested_candidate_id {
        return view.candidates.iter().find(|candidate| {
            candidate.id == id && candidate.status == RuntimeCandidateStatus::Ready
        });
    }
    view.candidates
        .iter()
        .find(|candidate| candidate.status == RuntimeCandidateStatus::Ready)
}

fn resolve_python_install(
    install: &PythonInstall,
    source_root: &Path,
    profile: &str,
    requirements: &super::manifest::RuntimeRequirements,
) -> RuntimeCandidateView {
    let mut warnings = Vec::new();
    let mut missing_imports = Vec::new();
    let mut missing_packages = Vec::new();
    let mut repair_actions = Vec::new();
    let mut status = RuntimeCandidateStatus::Ready;
    let mut message = None;
    let mut score = install.priority;

    if let Some(error) = &install.probe_error {
        status = RuntimeCandidateStatus::BrokenPython;
        message = Some(error.clone());
    } else if let Some(version_error) =
        python_version_error(install, requirements.python.as_deref())
    {
        status = RuntimeCandidateStatus::UnsupportedVersion;
        message = Some(version_error);
    } else if !architecture_matches(install.arch.as_deref()) {
        status = RuntimeCandidateStatus::WrongArchitecture;
        message = Some(format!(
            "Python architecture {} does not match this app architecture {}.",
            install.arch.as_deref().unwrap_or("unknown"),
            current_arch()
        ));
    } else {
        let import_report = check_python_imports(&install.executable, &requirements.imports);
        if !import_report.ok {
            missing_imports = import_report.missing_imports;
            status = RuntimeCandidateStatus::MissingCoreDeps;
            message = Some(import_report.message);
        } else if requirements.bridge_check {
            let bridge_report = check_bridge_runtime(
                &install.executable,
                source_root,
                profile,
                &requirements.requirements_file,
            );
            if !bridge_report.ok {
                missing_packages = bridge_report.missing_distributions;
                status = if missing_packages.is_empty() {
                    RuntimeCandidateStatus::BrokenBridge
                } else {
                    RuntimeCandidateStatus::MissingCoreDeps
                };
                message = Some(bridge_report.message);
                if !bridge_report.stderr.is_empty() {
                    warnings.push(shorten(&bridge_report.stderr, 400));
                }
                if !bridge_report.stdout.is_empty()
                    && status == RuntimeCandidateStatus::BrokenBridge
                {
                    warnings.push(shorten(&bridge_report.stdout, 240));
                }
            }
        }
    }

    if install.externally_managed {
        warnings.push("Python reports an externally-managed environment; Shinsekai will not modify it by default.".to_string());
    }
    if install.has_venv && !install.has_ensurepip {
        warnings.push(
            "Python has venv but not ensurepip; isolated runtime repair is disabled.".to_string(),
        );
    }
    if install.is_venv {
        warnings.push("This Python is already a virtual environment.".to_string());
    }
    warnings.extend(platform_compatibility_warnings(install));

    match status {
        RuntimeCandidateStatus::Ready => {
            score += 100_000;
            repair_actions.push(RuntimeRepairActionKind::Start);
        }
        RuntimeCandidateStatus::MissingCoreDeps => {
            repair_actions.extend(missing_core_deps_actions(install));
        }
        RuntimeCandidateStatus::BrokenPython
        | RuntimeCandidateStatus::BrokenBridge
        | RuntimeCandidateStatus::UnsupportedVersion
        | RuntimeCandidateStatus::WrongArchitecture => {
            repair_actions.push(RuntimeRepairActionKind::SelectDifferentRuntime);
        }
        RuntimeCandidateStatus::MissingOptionalDeps => {}
    }

    RuntimeCandidateView {
        id: install.id.clone(),
        python_id: Some(install.id.clone()),
        label: install.label.clone(),
        path: install.executable.display().to_string(),
        display_path: super::python_probe::display_path(&install.executable),
        kind: runtime_kind(install.kind),
        version: install.version.clone(),
        status,
        message,
        score,
        selected: false,
        managed: matches!(install.kind, PythonKind::Managed | PythonKind::ManagedVenv),
        missing_packages,
        missing_imports,
        python_version: None,
        warnings,
        repair_actions,
    }
}

fn check_python_imports(python: &Path, imports: &[String]) -> RuntimeCheckReport {
    if imports.is_empty() {
        return RuntimeCheckReport::ok();
    }
    let script = format!(
        "{}\nIMPORTS = {:?}\n{}",
        "import importlib, json",
        imports,
        r#"
missing = []
for name in IMPORTS:
    try:
        importlib.import_module(name)
    except Exception:
        missing.append(name)
print(json.dumps({"missing_imports": missing}))
raise SystemExit(1 if missing else 0)
"#
    );
    let mut command = Command::new(python);
    command.arg("-c").arg(script);
    python_env::configure_python_command(&mut command, python);
    let output = command.output();
    match output {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout).to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            let missing_imports = parse_missing_imports(&stdout);
            RuntimeCheckReport {
                ok: output.status.success() && missing_imports.is_empty(),
                python_ok: true,
                bridge_ok: false,
                message: if missing_imports.is_empty() {
                    stderr.trim().to_string()
                } else {
                    format!("Missing core imports: {}", missing_imports.join(", "))
                },
                missing_imports,
                missing_distributions: Vec::new(),
                stdout,
                stderr,
            }
        }
        Err(error) => RuntimeCheckReport {
            ok: false,
            python_ok: false,
            bridge_ok: false,
            missing_imports: Vec::new(),
            missing_distributions: Vec::new(),
            stderr: error.to_string(),
            stdout: String::new(),
            message: error.to_string(),
        },
    }
}

fn check_bridge_runtime(
    python: &Path,
    source_root: &Path,
    profile: &str,
    requirements_file: &str,
) -> RuntimeCheckReport {
    let bridge = source_root.join("frontend_bridge.py");
    let requirements = source_root.join(requirements_file);
    if !bridge.is_file() {
        return RuntimeCheckReport {
            ok: false,
            python_ok: true,
            bridge_ok: false,
            missing_imports: Vec::new(),
            missing_distributions: Vec::new(),
            stderr: String::new(),
            stdout: String::new(),
            message: format!("frontend_bridge.py not found at {}", bridge.display()),
        };
    }
    if !requirements.is_file() {
        return RuntimeCheckReport {
            ok: false,
            python_ok: true,
            bridge_ok: false,
            missing_imports: Vec::new(),
            missing_distributions: Vec::new(),
            stderr: String::new(),
            stdout: String::new(),
            message: format!("requirements file not found: {}", requirements.display()),
        };
    }

    let mut command = Command::new(python);
    command
        .arg(&bridge)
        .arg("--check-runtime")
        .arg("--json")
        .arg("--profile")
        .arg(profile)
        .arg("--project-root")
        .arg(source_root)
        .arg("--requirements-file")
        .arg(&requirements)
        .current_dir(source_root);
    python_env::configure_python_command(&mut command, python);
    let output = command.output();
    match output {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout).to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            let (missing_distributions, report_message) =
                parse_bridge_check_output(&stdout, &stderr);
            RuntimeCheckReport {
                ok: output.status.success(),
                python_ok: true,
                bridge_ok: output.status.success(),
                message: if output.status.success() {
                    "Runtime can start Shinsekai bridge.".to_string()
                } else if !report_message.is_empty() {
                    report_message
                } else {
                    "Shinsekai bridge runtime check failed.".to_string()
                },
                missing_imports: Vec::new(),
                missing_distributions,
                stdout,
                stderr,
            }
        }
        Err(error) => RuntimeCheckReport {
            ok: false,
            python_ok: true,
            bridge_ok: false,
            missing_imports: Vec::new(),
            missing_distributions: Vec::new(),
            stderr: error.to_string(),
            stdout: String::new(),
            message: error.to_string(),
        },
    }
}

fn parse_missing_imports(stdout: &str) -> Vec<String> {
    let parsed = parse_json_line(stdout);
    let Ok(value) = parsed else {
        return Vec::new();
    };
    value
        .get("missing_imports")
        .and_then(|value| value.as_array())
        .into_iter()
        .flatten()
        .filter_map(|value| value.as_str())
        .map(ToString::to_string)
        .collect()
}

fn parse_bridge_check_output(stdout: &str, stderr: &str) -> (Vec<String>, String) {
    if let Ok(value) = parse_json_line(stdout) {
        let missing = value
            .get("missingDistributions")
            .or_else(|| value.get("missing_distributions"))
            .and_then(|value| value.as_array())
            .into_iter()
            .flatten()
            .filter_map(|value| value.as_str())
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        let message = value
            .get("message")
            .and_then(|value| value.as_str())
            .unwrap_or("")
            .to_string();
        return (missing, message);
    }

    let text = format!("{stdout}\n{stderr}");
    let missing = text
        .split("missing Python runtime distributions:")
        .nth(1)
        .map(|tail| tail.lines().next().unwrap_or(""))
        .unwrap_or("")
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let message = text
        .lines()
        .find(|line| !line.trim().is_empty())
        .unwrap_or("")
        .trim()
        .to_string();
    (missing, message)
}

fn parse_json_line(text: &str) -> Result<serde_json::Value, serde_json::Error> {
    let trimmed = text.trim();
    if trimmed.starts_with('{') {
        return serde_json::from_str(trimmed);
    }
    let json_line = trimmed
        .lines()
        .rev()
        .map(str::trim)
        .find(|line| line.starts_with('{') && line.ends_with('}'))
        .unwrap_or(trimmed);
    serde_json::from_str(json_line)
}

fn python_version_error(install: &PythonInstall, requirement: Option<&str>) -> Option<String> {
    let requirement = requirement
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(">=3.10");
    let version = install
        .version
        .as_deref()
        .and_then(parse_python_version)
        .or_else(|| match (install.major, install.minor) {
            (Some(major), Some(minor)) => Some((major, minor, 0)),
            _ => None,
        })?;
    if python_version_satisfies(version, requirement) {
        return None;
    }
    Some(format!(
        "Python {}.{}.{} does not satisfy runtime requirement {requirement}.",
        version.0, version.1, version.2
    ))
}

fn python_version_satisfies(version: (u8, u8, u8), requirement: &str) -> bool {
    requirement
        .split(',')
        .map(str::trim)
        .filter(|clause| !clause.is_empty())
        .all(|clause| python_version_satisfies_clause(version, clause))
}

fn python_version_satisfies_clause(version: (u8, u8, u8), clause: &str) -> bool {
    for operator in [">=", "<=", "==", "=", ">", "<"] {
        if let Some(raw) = clause.strip_prefix(operator) {
            let Some(required) = parse_python_version(raw.trim()) else {
                return false;
            };
            return match operator {
                ">=" => version >= required,
                "<=" => version <= required,
                "==" | "=" => version == required,
                ">" => version > required,
                "<" => version < required,
                _ => false,
            };
        }
    }
    parse_python_version(clause)
        .map(|required| version == required)
        .unwrap_or(false)
}

fn parse_python_version(value: &str) -> Option<(u8, u8, u8)> {
    let parts = value
        .split(|character: char| !character.is_ascii_digit())
        .filter(|part| !part.is_empty())
        .take(3)
        .map(str::parse::<u8>)
        .collect::<Result<Vec<_>, _>>()
        .ok()?;
    Some((
        *parts.first()?,
        *parts.get(1).unwrap_or(&0),
        *parts.get(2).unwrap_or(&0),
    ))
}

fn architecture_matches(arch: Option<&str>) -> bool {
    let Some(arch) = arch.map(|value| value.to_ascii_lowercase()) else {
        return true;
    };
    let current = current_arch();
    match current {
        "x64" => matches!(arch.as_str(), "x86_64" | "amd64" | "x64"),
        "arm64" => matches!(arch.as_str(), "arm64" | "aarch64"),
        _ => true,
    }
}

fn platform_compatibility_warnings(install: &PythonInstall) -> Vec<String> {
    let mut warnings = Vec::new();
    if let Some(warning) = macos_rosetta_warning_for(
        current_arch(),
        install.arch.as_deref(),
        macos_process_translated(),
    ) {
        warnings.push(warning);
    }
    warnings
}

fn macos_rosetta_warning_for(
    app_arch: &str,
    python_arch: Option<&str>,
    process_translated: bool,
) -> Option<String> {
    if app_arch != "x64" || !process_translated {
        return None;
    }
    let python_arch = python_arch.unwrap_or("unknown").to_ascii_lowercase();
    if !matches!(python_arch.as_str(), "x86_64" | "amd64" | "x64") {
        return None;
    }
    Some(
        "This macOS app appears to be running under Rosetta with an Intel Python; native arm64 Python or an isolated runtime may improve compatibility with native packages.".to_string(),
    )
}

#[cfg(target_os = "macos")]
fn macos_process_translated() -> bool {
    Command::new("sysctl")
        .arg("-in")
        .arg("sysctl.proc_translated")
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| String::from_utf8_lossy(&output.stdout).trim() == "1")
        .unwrap_or(false)
}

#[cfg(not(target_os = "macos"))]
fn macos_process_translated() -> bool {
    false
}

fn runtime_kind(kind: PythonKind) -> RuntimeKind {
    match kind {
        PythonKind::Managed => RuntimeKind::Managed,
        PythonKind::ManagedVenv => RuntimeKind::ManagedVenv,
    }
}

fn missing_core_deps_actions(install: &PythonInstall) -> Vec<RuntimeRepairActionKind> {
    let mut actions = Vec::new();
    if can_create_managed_venv(install) {
        actions.push(RuntimeRepairActionKind::CreateManagedVenv);
    }
    if can_install_runtime_deps(install) {
        actions.push(RuntimeRepairActionKind::InstallRuntimeDeps);
    }
    actions.push(RuntimeRepairActionKind::SelectDifferentRuntime);
    actions
}

fn can_create_managed_venv(install: &PythonInstall) -> bool {
    install.has_venv && install.has_ensurepip
}

fn can_install_runtime_deps(install: &PythonInstall) -> bool {
    (install.has_pip || install.has_ensurepip) && !install.externally_managed
}

fn recommended_action(
    candidates: &[RuntimeCandidateView],
    selected_candidate_id: Option<&str>,
) -> Option<RuntimeRepairActionKind> {
    if selected_candidate_id.is_some() {
        return Some(RuntimeRepairActionKind::Start);
    }
    if candidates.iter().any(|candidate| {
        candidate
            .repair_actions
            .contains(&RuntimeRepairActionKind::CreateManagedVenv)
    }) {
        return Some(RuntimeRepairActionKind::CreateManagedVenv);
    }
    if candidates.iter().any(|candidate| {
        candidate
            .repair_actions
            .contains(&RuntimeRepairActionKind::InstallRuntimeDeps)
    }) {
        return Some(RuntimeRepairActionKind::InstallRuntimeDeps);
    }
    Some(RuntimeRepairActionKind::SelectDifferentRuntime)
}

fn scan_message(
    candidates: &[RuntimeCandidateView],
    selected_candidate_id: Option<&str>,
) -> Option<String> {
    if let Some(id) = selected_candidate_id {
        let candidate = candidates.iter().find(|candidate| candidate.id == id)?;
        return Some(format!("Ready to start with {}.", candidate.label));
    }
    if candidates.is_empty() {
        return Some("No Shinsekai managed Python runtime was found.".to_string());
    }
    if candidates
        .iter()
        .any(|candidate| candidate.status == RuntimeCandidateStatus::MissingCoreDeps)
    {
        return Some("Python was found, but Shinsekai core dependencies are missing.".to_string());
    }
    Some("No compatible Shinsekai managed runtime is ready. Restore the bundled runtime or repair its dependencies.".to_string())
}

fn shorten(value: &str, limit: usize) -> String {
    let trimmed = value.trim();
    if trimmed.len() <= limit {
        return trimmed.to_string();
    }
    format!("{}...", &trimmed[..limit])
}

impl RuntimeCheckReport {
    fn ok() -> Self {
        Self {
            ok: true,
            python_ok: true,
            bridge_ok: true,
            missing_imports: Vec::new(),
            missing_distributions: Vec::new(),
            stderr: String::new(),
            stdout: String::new(),
            message: String::new(),
        }
    }
}

#[cfg(test)]
mod tests;
