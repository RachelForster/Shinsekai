use std::{collections::HashMap, env, path::Path, process::Command};

use super::python_env;
use crate::path_contract::ExecutableSnapshot;

const PYTORCH_PROJECT_NAMES: &[&str] = &["torch", "torchvision", "torchaudio"];
const HOST_PYTORCH_STACK: &[(&str, &str)] = &[
    ("torch", "2.7.1"),
    ("torchvision", "0.22.1"),
    ("torchaudio", "2.7.1"),
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct PytorchInstallPlan {
    pub requirement_lines: Vec<String>,
    pub index_url: String,
    pub index_reason: String,
    pub expected_build: String,
    pub install_required: bool,
    pub force_reinstall: bool,
    pub detail: String,
}

pub(super) fn partition_requirement_lines(lines: &[String]) -> (Vec<String>, Vec<String>) {
    let mut pytorch_lines = Vec::new();
    let mut other_lines = Vec::new();
    for line in lines {
        let project_name = requirement_line_project_name(line);
        if project_name
            .as_deref()
            .is_some_and(|name| PYTORCH_PROJECT_NAMES.contains(&name))
        {
            pytorch_lines.push(line.trim_end_matches(['\r', '\n']).to_string());
        } else {
            other_lines.push(line.trim_end_matches(['\r', '\n']).to_string());
        }
    }
    (pytorch_lines, other_lines)
}

pub(super) fn install_plan(
    python: &Path,
    requirement_lines: &[String],
    pip_index_urls: &[String],
    working_directory: &Path,
) -> PytorchInstallPlan {
    let (index_url, index_reason) =
        wheel_index_url_for_this_machine(pip_index_urls, working_directory);
    let installed_versions = installed_versions(python, working_directory);
    build_install_plan(
        requirement_lines,
        &installed_versions,
        index_url,
        index_reason,
    )
}

pub(super) fn build_install_plan(
    requirement_lines: &[String],
    installed_versions: &HashMap<String, String>,
    index_url: String,
    index_reason: String,
) -> PytorchInstallPlan {
    let expected_build = index_build(&index_url);
    let has_pytorch_requirement = requirement_lines
        .iter()
        .filter_map(|line| requirement_line_project_name(line))
        .any(|name| PYTORCH_PROJECT_NAMES.contains(&name.as_str()));
    if !has_pytorch_requirement {
        return PytorchInstallPlan {
            requirement_lines: Vec::new(),
            index_url,
            index_reason,
            expected_build,
            install_required: false,
            force_reinstall: false,
            detail: "no active PyTorch requirements".to_string(),
        };
    }

    // Plugin/runtime requirement files only opt into PyTorch. The host owns
    // the exact shared binary stack so a broad plugin constraint cannot select
    // an untested latest release from the wheel index.
    let managed_requirement_lines = HOST_PYTORCH_STACK
        .iter()
        .map(|(name, version)| format!("{name}=={version}"))
        .collect::<Vec<_>>();
    let installed_stack = PYTORCH_PROJECT_NAMES
        .iter()
        .filter(|name| installed_versions.contains_key(**name))
        .count();
    let missing = HOST_PYTORCH_STACK
        .iter()
        .filter(|(name, _)| !installed_versions.contains_key(*name))
        .map(|(name, _)| (*name).to_string())
        .collect::<Vec<_>>();
    let version_mismatches = HOST_PYTORCH_STACK
        .iter()
        .filter_map(|(name, expected)| {
            let installed = installed_versions.get(*name)?;
            (public_version(installed) != *expected)
                .then(|| format!("{name}=={installed} (expected {expected})"))
        })
        .collect::<Vec<_>>();
    let build_mismatches = PYTORCH_PROJECT_NAMES
        .iter()
        .filter_map(|name| {
            let installed = installed_versions.get(*name)?;
            (!build_matches(installed, &expected_build)).then(|| format!("{name}=={installed}"))
        })
        .collect::<Vec<_>>();

    if !version_mismatches.is_empty() || !build_mismatches.is_empty() {
        let mut reasons = Vec::new();
        if !version_mismatches.is_empty() {
            reasons.push(format!(
                "version mismatch: {}",
                version_mismatches.join(", ")
            ));
        }
        if !build_mismatches.is_empty() {
            reasons.push(format!(
                "expected {} wheels, found {}",
                expected_build,
                build_mismatches.join(", ")
            ));
        }
        return PytorchInstallPlan {
            requirement_lines: managed_requirement_lines,
            index_url,
            index_reason,
            expected_build,
            install_required: true,
            force_reinstall: true,
            detail: reasons.join("; "),
        };
    }

    if !missing.is_empty() {
        return PytorchInstallPlan {
            requirement_lines: managed_requirement_lines,
            index_url,
            index_reason,
            expected_build,
            install_required: true,
            force_reinstall: installed_stack > 0,
            detail: format!("missing packages: {}", missing.join(", ")),
        };
    }

    PytorchInstallPlan {
        requirement_lines: managed_requirement_lines,
        index_url,
        index_reason,
        expected_build,
        install_required: false,
        force_reinstall: false,
        detail: "installed PyTorch stack matches host versions and wheel channel".to_string(),
    }
}

fn installed_versions(python: &Path, working_directory: &Path) -> HashMap<String, String> {
    let script = r#"
import importlib.metadata as metadata
for name in ("torch", "torchvision", "torchaudio"):
    try:
        print(name + "\t" + metadata.version(name))
    except metadata.PackageNotFoundError:
        pass
"#;
    let mut command = Command::new(python);
    command.arg("-c").arg(script).current_dir(working_directory);
    if python_env::configure_python_command(&mut command, python).is_err() {
        return HashMap::new();
    }
    let Ok(output) = command.output() else {
        return HashMap::new();
    };
    if !output.status.success() {
        return HashMap::new();
    }
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| line.split_once('\t'))
        .map(|(name, version)| (canonical_project_name(name), version.trim().to_string()))
        .collect()
}

fn requirement_line_project_name(line: &str) -> Option<String> {
    let mut segment = line.split('#').next()?.trim();
    if segment.is_empty() {
        return None;
    }
    let lower = segment.to_ascii_lowercase();
    if lower.starts_with("--") || lower.starts_with("-r ") || lower.starts_with("-c ") {
        return None;
    }
    if lower.starts_with("-e ") {
        segment = segment.get(3..)?.trim();
    }
    let first = segment.split_whitespace().next().unwrap_or(segment);
    if first.contains("://") || first.starts_with("git+") {
        return None;
    }
    let name = first
        .chars()
        .take_while(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-'))
        .collect::<String>();
    (!name.is_empty()).then(|| canonical_project_name(&name))
}

fn canonical_project_name(name: &str) -> String {
    name.to_ascii_lowercase().replace(['_', '.'], "-")
}

fn public_version(version: &str) -> &str {
    version.split('+').next().unwrap_or(version).trim()
}

fn index_build(index_url: &str) -> String {
    let candidate = index_url
        .trim_end_matches('/')
        .rsplit('/')
        .next()
        .unwrap_or("")
        .to_ascii_lowercase();
    if candidate == "cpu"
        || candidate.strip_prefix("cu").is_some_and(|digits| {
            !digits.is_empty() && digits.chars().all(|ch| ch.is_ascii_digit())
        })
    {
        candidate
    } else {
        String::new()
    }
}

fn installed_build(version: &str) -> String {
    let local = version
        .split_once('+')
        .map(|(_, local)| local)
        .unwrap_or("")
        .to_ascii_lowercase();
    local
        .split(['.', '-', '+'])
        .find(|part| {
            *part == "cpu"
                || part.strip_prefix("cu").is_some_and(|digits| {
                    !digits.is_empty() && digits.chars().all(|ch| ch.is_ascii_digit())
                })
        })
        .unwrap_or("")
        .to_string()
}

fn build_matches(version: &str, expected_build: &str) -> bool {
    if expected_build.is_empty() {
        return true;
    }
    let installed = installed_build(version);
    if expected_build == "cpu" {
        installed.is_empty() || installed == "cpu"
    } else {
        installed == expected_build
    }
}

pub(super) fn wheel_index_url_for_this_machine(
    pip_index_urls: &[String],
    working_directory: &Path,
) -> (String, String) {
    wheel_index_url_for_cuda_version(
        nvidia_smi_cuda_driver_version(working_directory),
        wheel_base_url(pip_index_urls),
    )
}

pub(super) fn wheel_base_url(pip_index_urls: &[String]) -> String {
    if let Ok(value) = env::var("SHINSEKAI_PYTORCH_WHEEL_BASE") {
        let trimmed = value.trim().trim_end_matches('/');
        if !trimmed.is_empty() {
            return trimmed.to_string();
        }
    }
    if let Some(prefer_china) = explicit_pytorch_region() {
        return if prefer_china {
            "https://mirrors.aliyun.com/pytorch-wheels".to_string()
        } else {
            "https://download.pytorch.org/whl".to_string()
        };
    }
    let configured_indexes = if pip_index_urls.is_empty() {
        pip_index_urls_from_env()
    } else {
        pip_index_urls.to_vec()
    };
    if pip_indexes_prefer_china(&configured_indexes) {
        "https://mirrors.aliyun.com/pytorch-wheels".to_string()
    } else {
        "https://download.pytorch.org/whl".to_string()
    }
}

fn explicit_pytorch_region() -> Option<bool> {
    let runtime_source = env::var("SHINSEKAI_RUNTIME_SOURCE")
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    if matches!(
        runtime_source.as_str(),
        "china" | "cn" | "mainland" | "mainland_china"
    ) {
        return Some(true);
    }
    if matches!(
        runtime_source.as_str(),
        "official" | "global" | "intl" | "international" | "overseas" | "us"
    ) {
        return Some(false);
    }
    let mirror_region = env::var("SHINSEKAI_MIRROR_REGION")
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    if matches!(
        mirror_region.as_str(),
        "china" | "cn" | "mainland" | "mainland_china"
    ) {
        return Some(true);
    }
    if matches!(
        mirror_region.as_str(),
        "official" | "global" | "intl" | "international" | "overseas" | "us"
    ) {
        return Some(false);
    }
    None
}

fn pip_index_urls_from_env() -> Vec<String> {
    let mut urls = Vec::new();
    for name in [
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URLS",
    ] {
        let Ok(raw) = env::var(name) else {
            continue;
        };
        for line in raw.lines() {
            for part in line.split(',') {
                let value = part.trim();
                if !value.is_empty() {
                    urls.push(value.to_string());
                }
            }
        }
    }
    urls
}

fn pip_indexes_prefer_china(pip_index_urls: &[String]) -> bool {
    let Some(primary) = pip_index_urls.first() else {
        return false;
    };
    let primary = primary.to_ascii_lowercase();
    [
        "pypi.tuna.tsinghua.edu.cn",
        "mirrors.ustc.edu.cn",
        "mirrors.hit.edu.cn",
        "mirrors.aliyun.com",
        "mirror.sjtu.edu.cn",
    ]
    .iter()
    .any(|domain| primary.contains(domain))
}

pub(super) fn wheel_index_url_for_cuda_version(
    version: Option<(u32, u32)>,
    base_url: String,
) -> (String, String) {
    let Some((major, minor)) = version else {
        return (
            format!("{base_url}/cpu"),
            "no_usable_nvidia_smi_cpu".to_string(),
        );
    };
    let tag = if (major, minor) >= (12, 8) {
        Some("cu128")
    } else if (major, minor) >= (12, 6) {
        Some("cu126")
    } else if major == 11 && minor >= 8 {
        Some("cu118")
    } else {
        None
    };
    let Some(tag) = tag else {
        return (
            format!("{base_url}/cpu"),
            format!("nvidia_driver_cuda_{major}.{minor}_cpu_fallback"),
        );
    };
    (
        format!("{base_url}/{tag}"),
        format!("nvidia_driver_cuda_{major}.{minor}_{tag}"),
    )
}

fn nvidia_smi_cuda_driver_version(working_directory: &Path) -> Option<(u32, u32)> {
    let executable = ExecutableSnapshot::capture("nvidia-smi").ok()?;
    executable.require_current().ok()?;
    let output = Command::new(executable.path())
        .current_dir(working_directory)
        .output()
        .ok()?;
    executable.require_current().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    parse_nvidia_smi_cuda_version(&stdout)
}

pub(super) fn parse_nvidia_smi_cuda_version(output: &str) -> Option<(u32, u32)> {
    let (_, tail) = output.split_once("CUDA Version:")?;
    let version_text = tail
        .trim_start()
        .chars()
        .take_while(|ch| ch.is_ascii_digit() || *ch == '.')
        .collect::<String>();
    let (major, minor) = version_text.split_once('.')?;
    Some((major.parse().ok()?, minor.parse().ok()?))
}

#[cfg(test)]
mod tests {
    use super::installed_versions;
    use std::path::Path;

    #[test]
    fn installed_versions_never_launches_a_relative_python_from_process_cwd() {
        assert!(installed_versions(Path::new("python"), Path::new(".")).is_empty());
    }
}
