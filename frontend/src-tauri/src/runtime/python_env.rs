use std::{
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};

pub(super) fn configure_python_command(command: &mut Command, python: &Path) {
    sanitize_python_environment(command);
    command.env("PYTHONUTF8", "1");
    configure_certifi_bundle(command, python);
}

pub(super) fn configure_pip_command(command: &mut Command, python: &Path) {
    configure_python_command(command, python);
    command.env("PIP_DISABLE_PIP_VERSION_CHECK", "1");
}

fn sanitize_python_environment(command: &mut Command) {
    command.env_remove("PYTHONHOME").env_remove("PYTHONPATH");
}

fn configure_certifi_bundle(command: &mut Command, python: &Path) {
    configure_certifi_bundle_for(
        command,
        python,
        env::var_os("SSL_CERT_FILE").is_some() || env::var_os("REQUESTS_CA_BUNDLE").is_some(),
    );
}

fn configure_certifi_bundle_for(command: &mut Command, python: &Path, already_configured: bool) {
    if already_configured {
        return;
    }
    let Some(cacert) = certifi_cacert_path_for_python(python) else {
        return;
    };
    command
        .env("SSL_CERT_FILE", &cacert)
        .env("REQUESTS_CA_BUNDLE", cacert);
}

fn certifi_cacert_path_for_python(python: &Path) -> Option<PathBuf> {
    for prefix in python_prefix_candidates(python) {
        if let Some(cacert) = certifi_cacert_path_in_prefix(&prefix) {
            return Some(cacert);
        }
    }
    None
}

fn certifi_cacert_path_in_prefix(prefix: &Path) -> Option<PathBuf> {
    let candidates = [
        prefix
            .join("Lib")
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem"),
        prefix
            .join("lib")
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem"),
    ];
    for candidate in candidates {
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    let lib = prefix.join("lib");
    let Ok(entries) = fs::read_dir(lib) else {
        return None;
    };
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if !name.starts_with("python") || !path.is_dir() {
            continue;
        }
        let candidate = path
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem");
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn python_prefix_candidates(python: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    push_python_prefix_candidate(&mut candidates, python);
    if let Ok(canonical) = python.canonicalize() {
        push_python_prefix_candidate(&mut candidates, &canonical);
    }
    candidates
}

fn push_python_prefix_candidate(candidates: &mut Vec<PathBuf>, python: &Path) {
    let Some(parent) = python.parent() else {
        return;
    };
    let parent_name = parent.file_name().and_then(|name| name.to_str());
    let prefix = match parent_name {
        Some("bin") | Some("Scripts") => parent.parent().unwrap_or(parent),
        _ => parent,
    };
    if !candidates.iter().any(|candidate| candidate == prefix) {
        candidates.push(prefix.to_path_buf());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn certifi_path_is_found_from_unix_python_prefix() {
        let temp_root = unique_temp_dir("runtime-certifi-unix");
        let python = temp_root.join("bin").join("python3.10");
        let cacert = temp_root
            .join("lib")
            .join("python3.10")
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem");
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::create_dir_all(cacert.parent().unwrap()).unwrap();
        fs::write(&python, "").unwrap();
        fs::write(&cacert, "").unwrap();

        assert_eq!(certifi_cacert_path_for_python(&python), Some(cacert));

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn certifi_path_is_found_from_windows_python_prefix() {
        let temp_root = unique_temp_dir("runtime-certifi-windows");
        let python = temp_root.join("Scripts").join("python.exe");
        let cacert = temp_root
            .join("Lib")
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem");
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::create_dir_all(cacert.parent().unwrap()).unwrap();
        fs::write(&python, "").unwrap();
        fs::write(&cacert, "").unwrap();

        assert_eq!(certifi_cacert_path_for_python(&python), Some(cacert));

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn configure_python_command_sets_certifi_bundle_when_available() {
        let temp_root = unique_temp_dir("runtime-certifi-command");
        let python = temp_root.join("bin").join("python3.10");
        let cacert = temp_root
            .join("lib")
            .join("python3.10")
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem");
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::create_dir_all(cacert.parent().unwrap()).unwrap();
        fs::write(&python, "").unwrap();
        fs::write(&cacert, "").unwrap();

        let mut command = Command::new(&python);
        sanitize_python_environment(&mut command);
        command.env("PYTHONUTF8", "1");
        configure_certifi_bundle_for(&mut command, &python, false);
        let envs = command
            .get_envs()
            .map(|(key, value)| {
                (
                    key.to_string_lossy().to_string(),
                    value.map(|value| value.to_string_lossy().to_string()),
                )
            })
            .collect::<Vec<_>>();

        assert!(envs.contains(&("PYTHONHOME".to_string(), None)));
        assert!(envs.contains(&("PYTHONPATH".to_string(), None)));
        assert!(envs.contains(&("PYTHONUTF8".to_string(), Some("1".to_string()))));
        assert!(envs.contains(&(
            "SSL_CERT_FILE".to_string(),
            Some(cacert.display().to_string())
        )));
        assert!(envs.contains(&(
            "REQUESTS_CA_BUNDLE".to_string(),
            Some(cacert.display().to_string())
        )));

        let _ = fs::remove_dir_all(temp_root);
    }

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        env::temp_dir().join(format!("shinsekai-{name}-{nonce}"))
    }
}
