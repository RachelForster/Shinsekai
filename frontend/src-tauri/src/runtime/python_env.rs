use std::{
    env,
    ffi::{OsStr, OsString},
    fs, io,
    path::{Path, PathBuf},
    process::Command,
};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use crate::path_contract::{
    canonicalize_directory_following_links_stably, canonicalize_directory_without_links,
    canonicalize_regular_file_following_links_stably, canonicalize_regular_file_without_links,
    files_have_same_identity, open_directory_without_links, path_has_no_link_components,
    path_is_filesystem_root, path_text_is_portable,
};

const CERTIFICATE_FILE_ENVIRONMENTS: &[&str] =
    &["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"];
const PIP_INPUT_FILE_ENVIRONMENTS: &[&str] = &[
    "PIP_CERT",
    "PIP_CLIENT_CERT",
    "PIP_CONFIG_FILE",
    "PIP_REQUIREMENT",
    "PIP_CONSTRAINT",
];
const PIP_OUTPUT_PATH_ENVIRONMENTS: &[&str] = &[
    "PIP_CACHE_DIR",
    "PIP_SRC",
    "PIP_TARGET",
    "PIP_PREFIX",
    "PIP_ROOT",
    "PIP_BUILD_TRACKER",
    "PIP_LOG",
];

pub(super) fn configure_python_command(command: &mut Command, python: &Path) -> io::Result<()> {
    sanitize_python_environment(command);
    command.env("PYTHONUTF8", "1").env("PYTHONNOUSERSITE", "1");
    configure_stable_working_directory(command, python)?;
    hide_python_child_window(command);
    configure_certificate_environment(command, python)
}

pub(super) fn configure_pip_command(command: &mut Command, python: &Path) -> io::Result<()> {
    configure_python_command(command, python)?;
    configure_pip_path_environment(command)?;
    command.env("PIP_DISABLE_PIP_VERSION_CHECK", "1");
    Ok(())
}

fn sanitize_python_environment(command: &mut Command) {
    command
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONUSERBASE")
        .env_remove("PYTHONPYCACHEPREFIX")
        .env_remove("PYTHONEXECUTABLE")
        .env_remove("__PYVENV_LAUNCHER__");
}

fn configure_stable_working_directory(command: &mut Command, python: &Path) -> io::Result<()> {
    let requested = command
        .get_current_dir()
        .map(Path::to_path_buf)
        .or_else(|| python.parent().map(Path::to_path_buf))
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "Python executable has no parent working directory",
            )
        })?;
    let current_directory = canonicalize_directory_without_links(&requested).map_err(|error| {
        io::Error::new(
            error.kind(),
            format!(
                "Python working directory must be an absolute, existing, non-link directory ({}): {error}",
                requested.display()
            ),
        )
    })?;
    command.current_dir(current_directory);
    Ok(())
}

fn hide_python_child_window(command: &mut Command) {
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(not(windows))]
    {
        let _ = command;
    }
}

fn configure_certificate_environment(command: &mut Command, python: &Path) -> io::Result<()> {
    let mut explicit_bundle = false;
    for name in CERTIFICATE_FILE_ENVIRONMENTS {
        let Some(path) = validated_regular_file_environment_value(name, env::var_os(name))? else {
            continue;
        };
        command.env(name, path);
        explicit_bundle = true;
    }
    if let Some(path) =
        validated_directory_environment_value("SSL_CERT_DIR", env::var_os("SSL_CERT_DIR"))?
    {
        command.env("SSL_CERT_DIR", path);
    }
    configure_certifi_bundle_for(command, python, explicit_bundle)
}

fn configure_certifi_bundle_for(
    command: &mut Command,
    python: &Path,
    already_configured: bool,
) -> io::Result<()> {
    if already_configured {
        return Ok(());
    }
    let Some(cacert) = certifi_cacert_path_for_python(python) else {
        return Ok(());
    };
    command
        .env("SSL_CERT_FILE", &cacert)
        .env("REQUESTS_CA_BUNDLE", cacert);
    Ok(())
}

fn configure_pip_path_environment(command: &mut Command) -> io::Result<()> {
    for name in PIP_INPUT_FILE_ENVIRONMENTS {
        let value = env::var_os(name);
        if *name == "PIP_CONFIG_FILE" && value.as_deref().is_some_and(is_platform_null_device_value)
        {
            command.env(name, value.expect("checked as present"));
            continue;
        }
        let Some(path) = validated_regular_file_environment_value(name, value)? else {
            continue;
        };
        command.env(name, path);
    }
    for name in PIP_OUTPUT_PATH_ENVIRONMENTS {
        let Some(path) = validated_absolute_environment_path(name, env::var_os(name))? else {
            continue;
        };
        if !path_has_no_link_components(&path) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("{name} contains a symbolic link or reparse-point component"),
            ));
        }
        command.env(name, path);
    }
    Ok(())
}

fn validated_regular_file_environment_value(
    name: &str,
    value: Option<OsString>,
) -> io::Result<Option<PathBuf>> {
    let Some(path) = validated_absolute_environment_path(name, value)? else {
        return Ok(None);
    };
    canonicalize_regular_file_following_links_stably(&path)
        .map(Some)
        .map_err(|error| {
            io::Error::new(
                error.kind(),
                format!(
                    "{name} must name an existing regular non-link file ({}): {error}",
                    path.display()
                ),
            )
        })
}

fn validated_directory_environment_value(
    name: &str,
    value: Option<OsString>,
) -> io::Result<Option<PathBuf>> {
    let Some(path) = validated_absolute_environment_path(name, value)? else {
        return Ok(None);
    };
    canonicalize_directory_following_links_stably(&path)
        .map(Some)
        .map_err(|error| {
            io::Error::new(
                error.kind(),
                format!(
                    "{name} must resolve stably to an existing non-link directory ({}): {error}",
                    path.display()
                ),
            )
        })
}

fn validated_absolute_environment_path(
    name: &str,
    value: Option<OsString>,
) -> io::Result<Option<PathBuf>> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_empty() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("{name} must not be empty"),
        ));
    }
    let path = PathBuf::from(value);
    if !path.is_absolute() || !path_text_is_portable(&path) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!(
                "{name} must be a portable absolute path and must not depend on the child working directory: {}",
                path.display()
            ),
        ));
    }
    if path_is_filesystem_root(&path) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("{name} must not be a filesystem root"),
        ));
    }
    Ok(Some(path))
}

#[cfg(unix)]
fn is_platform_null_device_value(value: &OsStr) -> bool {
    value == OsStr::new("/dev/null")
}

#[cfg(windows)]
fn is_platform_null_device_value(value: &OsStr) -> bool {
    value
        .to_str()
        .is_some_and(|value| value.eq_ignore_ascii_case("NUL"))
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
        if let Ok(candidate) = canonicalize_regular_file_without_links(&candidate) {
            return Some(candidate);
        }
    }

    let lib = prefix.join("lib");
    let Ok(lib_identity) = open_directory_without_links(&lib) else {
        return None;
    };
    let Ok(entries) = fs::read_dir(&lib) else {
        return None;
    };
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if !name.starts_with("python") {
            continue;
        }
        let Ok(path) = canonicalize_directory_without_links(&path) else {
            continue;
        };
        let candidate = path
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem");
        let Ok(candidate) = canonicalize_regular_file_without_links(&candidate) else {
            continue;
        };
        let Ok(current_lib) = open_directory_without_links(&lib) else {
            return None;
        };
        if !files_have_same_identity(&lib_identity, &current_lib).unwrap_or(false) {
            return None;
        }
        return Some(candidate);
    }
    None
}

fn python_prefix_candidates(python: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    push_python_prefix_candidate(&mut candidates, python);
    if let Ok(canonical) = canonicalize_regular_file_without_links(python) {
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
        configure_certifi_bundle_for(&mut command, &python, false).unwrap();
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
        assert!(envs.contains(&("PYTHONUSERBASE".to_string(), None)));
        assert!(envs.contains(&("PYTHONPYCACHEPREFIX".to_string(), None)));
        assert!(envs.contains(&("PYTHONEXECUTABLE".to_string(), None)));
        assert!(envs.contains(&("__PYVENV_LAUNCHER__".to_string(), None)));
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

    #[test]
    fn configure_python_command_uses_executable_parent_instead_of_process_cwd() {
        let temp_root = unique_temp_dir("runtime-python-cwd");
        let python_parent = temp_root.join("bin");
        let python = python_parent.join(if cfg!(windows) {
            "python.exe"
        } else {
            "python"
        });
        fs::create_dir_all(&python_parent).unwrap();
        fs::write(&python, "").unwrap();

        let mut command = Command::new(&python);
        configure_python_command(&mut command, &python).unwrap();

        assert_eq!(command.get_current_dir(), Some(python_parent.as_path()));
        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn configure_python_command_preserves_explicit_project_cwd() {
        let temp_root = unique_temp_dir("runtime-explicit-cwd");
        let python_parent = temp_root.join("bin");
        let project_root = temp_root.join("project");
        let python = python_parent.join(if cfg!(windows) {
            "python.exe"
        } else {
            "python"
        });
        fs::create_dir_all(&python_parent).unwrap();
        fs::create_dir_all(&project_root).unwrap();
        fs::write(&python, "").unwrap();

        let mut command = Command::new(&python);
        command.current_dir(&project_root);
        configure_python_command(&mut command, &python).unwrap();

        assert_eq!(command.get_current_dir(), Some(project_root.as_path()));
        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn relative_python_path_cannot_fall_back_to_process_working_directory() {
        let mut command = Command::new("python");
        let error = configure_python_command(&mut command, Path::new("python")).unwrap_err();

        assert!(error.to_string().contains("working directory"));
        assert!(command.get_current_dir().is_none());
    }

    #[test]
    fn environment_file_paths_must_be_absolute_and_existing() {
        let relative = validated_regular_file_environment_value(
            "SSL_CERT_FILE",
            Some(OsString::from("certs/cacert.pem")),
        )
        .unwrap_err();
        assert!(relative.to_string().contains("absolute path"));

        let missing = unique_temp_dir("runtime-missing-cert").join("cacert.pem");
        let error = validated_regular_file_environment_value(
            "SSL_CERT_FILE",
            Some(missing.into_os_string()),
        )
        .unwrap_err();
        assert!(error.to_string().contains("existing regular non-link file"));
    }

    #[cfg(unix)]
    #[test]
    fn environment_directory_aliases_resolve_to_a_stable_non_link_target() {
        use std::os::unix::fs::symlink;

        let temp_root = unique_temp_dir("runtime-directory-environment-link");
        let real = temp_root.join("real-certs");
        let alias = temp_root.join("certs");
        fs::create_dir_all(&real).unwrap();
        symlink(&real, &alias).unwrap();

        assert_eq!(
            validated_directory_environment_value("SSL_CERT_DIR", Some(alias.into_os_string()))
                .unwrap(),
            Some(real.canonicalize().unwrap())
        );

        let _ = fs::remove_dir_all(temp_root);
    }

    #[test]
    fn pip_output_paths_must_not_depend_on_child_working_directory() {
        let error = validated_absolute_environment_path(
            "PIP_CACHE_DIR",
            Some(OsString::from(".pip-cache")),
        )
        .unwrap_err();

        assert!(error.to_string().contains("child working directory"));
    }

    #[cfg(unix)]
    #[test]
    fn certifi_path_does_not_cross_a_symbolic_link() {
        use std::os::unix::fs::symlink;

        let temp_root = unique_temp_dir("runtime-certifi-link");
        let python = temp_root.join("bin").join("python3.10");
        let external = temp_root.join("external");
        let linked_python_dir = temp_root.join("lib").join("python3.10");
        let cacert = external
            .join("site-packages")
            .join("certifi")
            .join("cacert.pem");
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::create_dir_all(cacert.parent().unwrap()).unwrap();
        fs::write(&python, "").unwrap();
        fs::write(&cacert, "").unwrap();
        fs::create_dir_all(linked_python_dir.parent().unwrap()).unwrap();
        symlink(&external, &linked_python_dir).unwrap();

        assert_eq!(certifi_cacert_path_for_python(&python), None);

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
