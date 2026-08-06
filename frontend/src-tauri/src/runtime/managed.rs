use std::{
    collections::HashSet,
    error::Error,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    process::{Command, ExitStatus, Stdio},
    sync::mpsc::{self, RecvTimeoutError},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{Emitter, Manager, Runtime};

use super::{manifest::RuntimeRequirements, python_env, pytorch};
use crate::path_contract::{
    canonicalize_regular_file_without_links, files_have_same_identity, metadata_is_link,
    open_directory_without_links, open_regular_file_without_links, path_has_no_link_components,
    path_is_filesystem_root, path_text_is_portable,
};

type RuntimeResult<T> = Result<T, Box<dyn Error>>;
const RUNTIME_PROGRESS_EVENT: &str = "shinsekai:runtime-progress";

fn configure_pip_install_command(
    command: &mut Command,
    python: &Path,
    pip_index_url: Option<&str>,
) -> RuntimeResult<()> {
    python_env::configure_pip_command(command, python)?;
    if let Some(url) = pip_index_url.map(str::trim).filter(|url| !url.is_empty()) {
        command.arg("-i").arg(url);
    }
    Ok(())
}

fn ensure_python_pip_available(python: &Path) -> RuntimeResult<()> {
    if check_python_pip(python).is_ok() {
        return Ok(());
    }

    let mut ensurepip = Command::new(python);
    ensurepip
        .arg("-m")
        .arg("ensurepip")
        .arg("--upgrade")
        .arg("--default-pip");
    python_env::configure_pip_command(&mut ensurepip, python)?;
    if let Err(error) = run_command(&mut ensurepip, "bootstrap Python pip with ensurepip") {
        return Err(format!(
            "Python pip bootstrap failed for {}: {error}",
            python.display()
        )
        .into());
    }

    check_python_pip(python).map_err(|error| {
        format!(
            "Python pip is still not available for {} after ensurepip bootstrap: {}",
            python.display(),
            error
        )
        .into()
    })
}

fn check_python_pip(python: &Path) -> RuntimeResult<()> {
    let mut command = Command::new(python);
    command.arg("-m").arg("pip").arg("--version");
    python_env::configure_pip_command(&mut command, python)?;
    run_command(&mut command, "check Python pip")
}

fn install_runtime_requirements<F>(
    python: &Path,
    requirements_path: &Path,
    temporary_directory: &Path,
    pip_index_urls: &[String],
    mut on_log_line: F,
) -> RuntimeResult<()>
where
    F: FnMut(&str),
{
    let python_identity = open_regular_file_without_links(python).map_err(|error| {
        format!(
            "runtime Python must be a regular non-link file {}: {error}",
            python.display()
        )
    })?;
    ensure_python_pip_available(python)?;
    require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
    let mut requirements_file =
        open_regular_file_without_links(requirements_path).map_err(|error| {
            format!(
                "runtime requirements must be a regular non-link file {}: {error}",
                requirements_path.display()
            )
        })?;
    let mut requirements_text = String::new();
    requirements_file
        .read_to_string(&mut requirements_text)
        .map_err(|error| {
            format!(
                "read runtime requirements file {} failed: {error}",
                requirements_path.display()
            )
        })?;
    let requirement_lines = requirements_text
        .lines()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let requirement_inputs = capture_requirement_inputs(requirements_path, &requirement_lines)?;
    let (torch_lines, other_lines) = pytorch::partition_requirement_lines(&requirement_lines);
    let other_lines = rebase_requirement_file_directives(requirements_path, &other_lines)?;
    let split_torch = !torch_lines.is_empty() && !cfg!(target_os = "macos");

    if split_torch {
        let plan = pytorch::install_plan(python, &torch_lines, pip_index_urls, temporary_directory);
        on_log_line(&format!(
            "PyTorch plan: index={} ({}), install={}, force_reinstall={}: {}",
            plan.index_url,
            plan.index_reason,
            plan.install_required,
            plan.force_reinstall,
            plan.detail,
        ));
        let torch_requirements = write_temp_requirements(
            temporary_directory,
            "shinsekai-torch",
            &plan.requirement_lines,
        )?;
        let other_requirements =
            write_temp_requirements(temporary_directory, "shinsekai-runtime", &other_lines)?;
        let result = (|| {
            if plan.install_required {
                require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
                torch_requirements.require_current_identity()?;
                let mut install_torch = pytorch_install_command(
                    python,
                    &torch_requirements,
                    &plan.index_url,
                    plan.force_reinstall,
                )?;
                run_command_with_live_log(
                    &mut install_torch,
                    "install Shinsekai PyTorch runtime dependencies",
                    &mut on_log_line,
                )?;
                require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
                torch_requirements.require_current_identity()?;
                if plan.force_reinstall {
                    let mut repair_dependencies = pytorch_install_command(
                        python,
                        &torch_requirements,
                        &plan.index_url,
                        false,
                    )?;
                    run_command_with_live_log(
                        &mut repair_dependencies,
                        "repair Shinsekai PyTorch runtime dependencies",
                        &mut on_log_line,
                    )?;
                    require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
                    torch_requirements.require_current_identity()?;
                }
            }
            if !has_non_comment_requirement(&other_lines) {
                return Ok(());
            }
            install_runtime_requirements_file_with_indexes(
                python,
                &python_identity,
                &other_requirements,
                &other_requirements.identity,
                pip_index_urls,
                Some(&torch_requirements),
                &requirement_inputs,
                &mut on_log_line,
            )
        })();
        drop(other_requirements);
        drop(torch_requirements);
        return result;
    }

    install_runtime_requirements_file_with_indexes(
        python,
        &python_identity,
        requirements_path,
        &requirements_file,
        pip_index_urls,
        None,
        &requirement_inputs,
        &mut on_log_line,
    )
}

fn require_open_regular_file_identity(
    path: &Path,
    expected: &fs::File,
    field: &str,
) -> RuntimeResult<()> {
    let current = open_regular_file_without_links(path)?;
    if !files_have_same_identity(expected, &current)? {
        return Err(format!("{field} changed identity: {}", path.display()).into());
    }
    Ok(())
}

fn require_open_directory_identity(
    path: &Path,
    expected: &fs::File,
    field: &str,
) -> RuntimeResult<()> {
    let current = open_directory_without_links(path)?;
    if !files_have_same_identity(expected, &current)? {
        return Err(format!("{field} changed identity: {}", path.display()).into());
    }
    Ok(())
}

#[derive(Debug)]
struct RequirementInputSnapshot {
    path: PathBuf,
    identity: fs::File,
}

impl RequirementInputSnapshot {
    fn require_current_identity(&self) -> RuntimeResult<()> {
        require_open_regular_file_identity(
            &self.path,
            &self.identity,
            "included runtime requirements file",
        )
    }
}

#[derive(Debug)]
struct RequirementFileDirective {
    option: &'static str,
    value: String,
}

fn requirement_file_directive(line: &str) -> RuntimeResult<Option<RequirementFileDirective>> {
    let trimmed = line.trim();
    for option in ["-r", "--requirement", "-c", "--constraint"] {
        let Some(remainder) = trimmed.strip_prefix(option) else {
            continue;
        };
        let value = if let Some(value) = remainder.strip_prefix('=') {
            value.trim()
        } else if remainder.chars().next().is_some_and(char::is_whitespace) {
            remainder.trim()
        } else {
            continue;
        };
        if value.is_empty() {
            return Err(format!("{option} requires an exact requirements file path").into());
        }
        let unquoted = match (value.chars().next(), value.chars().last()) {
            (Some('"'), Some('"')) | (Some('\''), Some('\'')) if value.len() >= 2 => {
                &value[1..value.len() - 1]
            }
            (Some('"'), _) | (Some('\''), _) | (_, Some('"')) | (_, Some('\'')) => {
                return Err(
                    format!("{option} contains an unmatched requirements file path quote").into(),
                );
            }
            _ => value,
        };
        if unquoted.is_empty()
            || unquoted
                .chars()
                .any(|character| character <= '\u{1f}' || character == '\u{7f}')
        {
            return Err(format!("{option} contains a non-portable requirements file path").into());
        }
        if !value.starts_with(['"', '\''])
            && unquoted
                .chars()
                .any(|character| character.is_whitespace() || character == '#')
        {
            return Err(format!(
                "{option} requirements file paths containing spaces or # must be quoted"
            )
            .into());
        }
        return Ok(Some(RequirementFileDirective {
            option,
            value: unquoted.to_string(),
        }));
    }
    Ok(None)
}

fn local_requirement_input_path(
    source_path: &Path,
    directive: &RequirementFileDirective,
) -> RuntimeResult<Option<PathBuf>> {
    let value = directive.value.as_str();
    if value.starts_with("http://") || value.starts_with("https://") {
        return Ok(None);
    }
    if value.contains("://") || value.contains("${") || value.contains("$(") {
        return Err(format!(
            "{} uses an unsupported dynamic or non-HTTP requirements source: {value}",
            directive.option
        )
        .into());
    }
    let requested = Path::new(value);
    let candidate = if requested.is_absolute() {
        requested.to_path_buf()
    } else {
        source_path
            .parent()
            .ok_or_else(|| {
                format!(
                    "requirements file has no parent directory: {}",
                    source_path.display()
                )
            })?
            .join(requested)
    };
    canonicalize_regular_file_without_links(&candidate)
        .map(Some)
        .map_err(|error| {
            format!(
                "{} must reference an existing regular non-link requirements file ({}): {error}",
                directive.option,
                candidate.display()
            )
            .into()
        })
}

fn capture_requirement_inputs(
    source_path: &Path,
    lines: &[String],
) -> RuntimeResult<Vec<RequirementInputSnapshot>> {
    let mut snapshots = Vec::new();
    let mut visited = HashSet::new();
    capture_requirement_inputs_from(source_path, lines, &mut visited, &mut snapshots)?;
    Ok(snapshots)
}

fn capture_requirement_inputs_from(
    source_path: &Path,
    lines: &[String],
    visited: &mut HashSet<PathBuf>,
    snapshots: &mut Vec<RequirementInputSnapshot>,
) -> RuntimeResult<()> {
    for line in lines {
        let Some(directive) = requirement_file_directive(line)? else {
            continue;
        };
        let Some(path) = local_requirement_input_path(source_path, &directive)? else {
            continue;
        };
        if !visited.insert(path.clone()) {
            continue;
        }
        let mut identity = open_regular_file_without_links(&path)?;
        let mut text = String::new();
        identity.read_to_string(&mut text).map_err(|error| {
            format!(
                "read included runtime requirements file {} failed: {error}",
                path.display()
            )
        })?;
        let snapshot = RequirementInputSnapshot { path, identity };
        snapshot.require_current_identity()?;
        let nested_lines = text.lines().map(ToString::to_string).collect::<Vec<_>>();
        capture_requirement_inputs_from(&snapshot.path, &nested_lines, visited, snapshots)?;
        snapshots.push(snapshot);
    }
    Ok(())
}

fn pip_requirement_path_literal(path: &Path) -> RuntimeResult<String> {
    if !path_text_is_portable(path) {
        return Err(format!(
            "requirements include path is not portable: {}",
            path.display()
        )
        .into());
    }
    let text = path.to_str().ok_or_else(|| {
        format!(
            "requirements include path is not Unicode: {}",
            path.display()
        )
    })?;
    #[cfg(windows)]
    let escaped = text.replace('\\', "/").replace('"', "\\\"");
    #[cfg(not(windows))]
    let escaped = text.replace('\\', "\\\\").replace('"', "\\\"");
    Ok(format!("\"{escaped}\""))
}

fn rebase_requirement_file_directives(
    source_path: &Path,
    lines: &[String],
) -> RuntimeResult<Vec<String>> {
    lines
        .iter()
        .map(|line| {
            let Some(directive) = requirement_file_directive(line)? else {
                return Ok(line.clone());
            };
            let Some(path) = local_requirement_input_path(source_path, &directive)? else {
                return Ok(line.clone());
            };
            Ok(format!(
                "{} {}",
                directive.option,
                pip_requirement_path_literal(&path)?
            ))
        })
        .collect()
}

fn require_requirement_input_identities(
    snapshots: &[RequirementInputSnapshot],
) -> RuntimeResult<()> {
    for snapshot in snapshots {
        snapshot.require_current_identity()?;
    }
    Ok(())
}

fn install_runtime_requirements_file_with_indexes<F>(
    python: &Path,
    python_identity: &fs::File,
    requirements_path: &Path,
    requirements_identity: &fs::File,
    pip_index_urls: &[String],
    constraints: Option<&OwnedTemporaryRequirements>,
    requirement_inputs: &[RequirementInputSnapshot],
    mut on_log_line: F,
) -> RuntimeResult<()>
where
    F: FnMut(&str),
{
    let mut errors = Vec::new();

    if pip_index_urls.is_empty() {
        require_open_regular_file_identity(python, python_identity, "runtime Python")?;
        require_open_regular_file_identity(
            requirements_path,
            requirements_identity,
            "runtime requirements file",
        )?;
        let mut install = pip_install_command(python, requirements_path, None)?;
        if let Some(constraints) = constraints {
            constraints.require_current_identity()?;
        }
        require_requirement_input_identities(requirement_inputs)?;
        apply_pip_constraints(&mut install, constraints.map(|value| value.as_ref()));
        let result = run_command_with_live_log(
            &mut install,
            "install Shinsekai runtime dependencies",
            on_log_line,
        );
        require_open_regular_file_identity(python, python_identity, "runtime Python")?;
        require_open_regular_file_identity(
            requirements_path,
            requirements_identity,
            "runtime requirements file",
        )?;
        if let Some(constraints) = constraints {
            constraints.require_current_identity()?;
        }
        require_requirement_input_identities(requirement_inputs)?;
        return result;
    }

    for pip_index_url in pip_index_urls {
        require_open_regular_file_identity(python, python_identity, "runtime Python")?;
        require_open_regular_file_identity(
            requirements_path,
            requirements_identity,
            "runtime requirements file",
        )?;
        let mut install = pip_install_command(python, requirements_path, Some(pip_index_url))?;
        if let Some(constraints) = constraints {
            constraints.require_current_identity()?;
        }
        require_requirement_input_identities(requirement_inputs)?;
        apply_pip_constraints(&mut install, constraints.map(|value| value.as_ref()));
        on_log_line(&format!("Using pip index: {}", pip_index_url.trim()));
        let result = run_command_with_live_log(
            &mut install,
            "install Shinsekai runtime dependencies",
            &mut on_log_line,
        );
        require_open_regular_file_identity(python, python_identity, "runtime Python")?;
        require_open_regular_file_identity(
            requirements_path,
            requirements_identity,
            "runtime requirements file",
        )?;
        if let Some(constraints) = constraints {
            constraints.require_current_identity()?;
        }
        require_requirement_input_identities(requirement_inputs)?;
        match result {
            Ok(()) => return Ok(()),
            Err(error) => errors.push(format!("{}: {}", pip_index_url.trim(), error)),
        }
    }
    Err(format!(
        "install Shinsekai runtime dependencies failed from all configured pip indexes: {}",
        errors.join("; ")
    )
    .into())
}

#[derive(Debug)]
struct OwnedTemporaryRequirements {
    path: PathBuf,
    identity: fs::File,
    parent_path: PathBuf,
    parent_identity: fs::File,
}

impl std::ops::Deref for OwnedTemporaryRequirements {
    type Target = Path;

    fn deref(&self) -> &Self::Target {
        &self.path
    }
}

impl AsRef<Path> for OwnedTemporaryRequirements {
    fn as_ref(&self) -> &Path {
        &self.path
    }
}

impl OwnedTemporaryRequirements {
    fn require_current_identity(&self) -> RuntimeResult<()> {
        let current_parent = open_directory_without_links(&self.parent_path)?;
        let current = open_regular_file_without_links(&self.path)?;
        if !files_have_same_identity(&self.parent_identity, &current_parent)?
            || !files_have_same_identity(&self.identity, &current)?
        {
            return Err(format!(
                "runtime temporary requirements path changed identity: {}",
                self.path.display()
            )
            .into());
        }
        Ok(())
    }
}

impl Drop for OwnedTemporaryRequirements {
    fn drop(&mut self) {
        if self.require_current_identity().is_ok() {
            let _ = fs::remove_file(&self.path);
        }
    }
}

fn write_temp_requirements(
    temporary_directory: &Path,
    prefix: &str,
    lines: &[String],
) -> RuntimeResult<OwnedTemporaryRequirements> {
    if !temporary_directory.is_absolute() {
        return Err(format!(
            "runtime temporary directory must be absolute: {}",
            temporary_directory.display()
        )
        .into());
    }
    let parent = prepare_runtime_directory(temporary_directory, "runtime temporary directory")?;
    let parent_identity = open_directory_without_links(&parent)?;
    let filename = format!(
        "{}-{}-{}.txt",
        prefix,
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    );
    let path = parent.join(filename);
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)?;
    file.write_all(lines.join("\n").as_bytes())?;
    file.sync_all()?;
    let temporary_requirements = OwnedTemporaryRequirements {
        path,
        identity: file,
        parent_path: parent,
        parent_identity,
    };
    temporary_requirements.require_current_identity()?;
    Ok(temporary_requirements)
}

fn has_non_comment_requirement(lines: &[String]) -> bool {
    lines.iter().any(|line| {
        let trimmed = line.split('#').next().unwrap_or("").trim();
        !trimmed.is_empty() && !trimmed.starts_with('#')
    })
}

fn pip_install_command(
    python: &Path,
    requirements_path: &Path,
    pip_index_url: Option<&str>,
) -> RuntimeResult<Command> {
    let mut install = Command::new(python);
    install.arg("-m").arg("pip").arg("install");
    configure_pip_install_command(&mut install, python, pip_index_url)?;
    install.arg("-r").arg(requirements_path);
    Ok(install)
}

fn apply_pip_constraints(command: &mut Command, constraints_path: Option<&Path>) {
    if let Some(path) = constraints_path {
        command.arg("-c").arg(path);
    }
}

fn pytorch_install_command(
    python: &Path,
    requirements_path: &Path,
    index_url: &str,
    force_stack_only: bool,
) -> RuntimeResult<Command> {
    let mut install = pip_install_command(python, requirements_path, None)?;
    install
        .arg("--index-url")
        .arg(index_url)
        .arg("--extra-index-url")
        .arg("https://pypi.org/simple");
    if force_stack_only {
        // Without --no-deps, pip applies --force-reinstall to every resolved
        // transitive dependency. A following plain install repairs only
        // dependencies that are missing or genuinely incompatible.
        install
            .arg("--upgrade")
            .arg("--force-reinstall")
            .arg("--no-deps");
    }
    Ok(install)
}

pub fn install_runtime_dependencies<R: Runtime, M: Manager<R> + Emitter<R>>(
    app: &M,
    source_root: &Path,
    python: &Path,
    candidate_id: &str,
    profile: &str,
    requirements: &RuntimeRequirements,
    pip_index_urls: &[String],
) -> RuntimeResult<PathBuf> {
    let source_root_identity = open_directory_without_links(source_root).map_err(|error| {
        format!(
            "Shinsekai source root must be a regular non-link directory {}: {error}",
            source_root.display()
        )
    })?;
    let python_identity = open_regular_file_without_links(python).map_err(|error| {
        format!(
            "runtime Python must be a regular non-link file {}: {error}",
            python.display()
        )
    })?;
    let runtime_home = runtime_home(app)?;
    let install_lock = acquire_install_lock(&runtime_home)?;
    require_open_directory_identity(source_root, &source_root_identity, "Shinsekai source root")?;
    require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
    let candidate_id = safe_component(candidate_id);
    let requirements_path = requirements_path(source_root, &requirements.requirements_file);
    emit_runtime_progress(
        app,
        "installingDeps",
        Some(candidate_id.clone()),
        Some("local".to_string()),
        None,
        None,
        None,
        Some("Installing Shinsekai runtime dependencies"),
        None,
    );
    install_runtime_requirements(
        python,
        &requirements_path,
        &runtime_home,
        pip_index_urls,
        |line| {
            emit_runtime_progress(
                app,
                "installingDeps",
                Some(candidate_id.to_string()),
                Some("local".to_string()),
                None,
                None,
                None,
                Some("Installing Shinsekai runtime dependencies"),
                Some(line),
            );
        },
    )?;
    install_lock.require_current_identity()?;
    require_open_directory_identity(source_root, &source_root_identity, "Shinsekai source root")?;
    require_open_regular_file_identity(python, &python_identity, "runtime Python")?;

    emit_runtime_progress(
        app,
        "checkingBridge",
        Some(candidate_id.clone()),
        Some("local".to_string()),
        Some(2),
        Some(3),
        None,
        Some("Checking repaired runtime"),
        None,
    );
    verify_python_runtime(source_root, python, profile, requirements)?;
    install_lock.require_current_identity()?;
    require_open_directory_identity(source_root, &source_root_identity, "Shinsekai source root")?;
    require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
    emit_runtime_progress(
        app,
        "ready",
        Some(candidate_id),
        Some("local".to_string()),
        Some(3),
        Some(3),
        None,
        Some("Runtime dependencies are ready"),
        None,
    );
    Ok(python.to_path_buf())
}

fn verify_python_runtime(
    source_root: &Path,
    python: &Path,
    profile: &str,
    requirements: &RuntimeRequirements,
) -> RuntimeResult<()> {
    let source_root_identity = open_directory_without_links(source_root)?;
    let python_identity = open_regular_file_without_links(python)?;
    let bridge = source_root.join("frontend_bridge.py");
    let requirements_path = requirements_path(source_root, &requirements.requirements_file);
    let bridge_identity = open_regular_file_without_links(&bridge).map_err(|error| {
        format!(
            "Shinsekai bridge must be a regular non-link file {}: {error}",
            bridge.display()
        )
    })?;
    let requirements_identity =
        open_regular_file_without_links(&requirements_path).map_err(|error| {
            format!(
                "runtime requirements must be a regular non-link file {}: {error}",
                requirements_path.display()
            )
        })?;
    require_open_directory_identity(source_root, &source_root_identity, "Shinsekai source root")?;
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
        .arg(&requirements_path)
        .current_dir(source_root);
    python_env::configure_python_command(&mut command, python)?;
    run_command(&mut command, "check Shinsekai runtime")?;
    require_open_directory_identity(source_root, &source_root_identity, "Shinsekai source root")?;
    require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
    require_open_regular_file_identity(&bridge, &bridge_identity, "Shinsekai bridge")?;
    require_open_regular_file_identity(
        &requirements_path,
        &requirements_identity,
        "runtime requirements file",
    )?;
    verify_python_imports(python, &requirements.imports)
}

fn verify_python_imports(python: &Path, modules: &[String]) -> RuntimeResult<()> {
    if modules.is_empty() {
        return Ok(());
    }
    let python_identity = open_regular_file_without_links(python)?;
    let script = concat!(
        "import importlib, sys\n",
        "missing = []\n",
        "for name in sys.argv[1:]:\n",
        "    try:\n",
        "        importlib.import_module(name)\n",
        "    except Exception as exc:\n",
        "        missing.append(f'{name}: {exc}')\n",
        "if missing:\n",
        "    raise SystemExit('runtime import check failed: ' + '; '.join(missing))\n",
    );
    let mut command = Command::new(python);
    command.arg("-c").arg(script).args(modules);
    python_env::configure_python_command(&mut command, python)?;
    let result = run_command(&mut command, "check Shinsekai runtime imports");
    require_open_regular_file_identity(python, &python_identity, "runtime Python")?;
    result
}

fn run_command(command: &mut Command, label: &str) -> RuntimeResult<()> {
    let output = command
        .output()
        .map_err(|error| format!("{label} failed to start: {error}"))?;
    if output.status.success() {
        return Ok(());
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(format!(
        "{label} failed with status {}. stdout: {} stderr: {}",
        output
            .status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "terminated".to_string()),
        stdout.trim(),
        stderr.trim()
    )
    .into())
}

fn run_command_with_live_log<F>(
    command: &mut Command,
    label: &str,
    mut on_log_line: F,
) -> RuntimeResult<()>
where
    F: FnMut(&str),
{
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn()?;
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let (tx, rx) = mpsc::channel::<(OutputStream, String)>();
    let mut readers = Vec::new();

    if let Some(stdout) = stdout {
        readers.push(spawn_output_reader(
            OutputStream::Stdout,
            stdout,
            tx.clone(),
        ));
    }
    if let Some(stderr) = stderr {
        readers.push(spawn_output_reader(
            OutputStream::Stderr,
            stderr,
            tx.clone(),
        ));
    }
    drop(tx);

    let mut stdout_lines = Vec::new();
    let mut stderr_lines = Vec::new();
    let status = wait_for_command_with_live_log(
        &mut child,
        &rx,
        &mut stdout_lines,
        &mut stderr_lines,
        &mut on_log_line,
    )?;
    for entry in rx {
        push_output_line(
            entry,
            &mut stdout_lines,
            &mut stderr_lines,
            &mut on_log_line,
        );
    }
    for reader in readers {
        let _ = reader.join();
    }

    if status.success() {
        return Ok(());
    }
    Err(format!(
        "{label} failed with status {}. stdout: {} stderr: {}",
        status
            .code()
            .map(|code| code.to_string())
            .unwrap_or_else(|| "terminated".to_string()),
        stdout_lines.join("\n").trim(),
        stderr_lines.join("\n").trim()
    )
    .into())
}

fn wait_for_command_with_live_log<F>(
    child: &mut std::process::Child,
    rx: &mpsc::Receiver<(OutputStream, String)>,
    stdout_lines: &mut Vec<String>,
    stderr_lines: &mut Vec<String>,
    on_log_line: &mut F,
) -> RuntimeResult<ExitStatus>
where
    F: FnMut(&str),
{
    let mut last_status_check = Instant::now();
    loop {
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(entry) => push_output_line(entry, stdout_lines, stderr_lines, on_log_line),
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => {
                return Ok(child.wait()?);
            }
        }
        if last_status_check.elapsed() >= Duration::from_millis(50) {
            if let Some(status) = child.try_wait()? {
                return Ok(status);
            }
            last_status_check = Instant::now();
        }
    }
}

fn push_output_line<F>(
    (stream, line): (OutputStream, String),
    stdout_lines: &mut Vec<String>,
    stderr_lines: &mut Vec<String>,
    on_log_line: &mut F,
) where
    F: FnMut(&str),
{
    if line.trim().is_empty() {
        return;
    }
    on_log_line(&line);
    match stream {
        OutputStream::Stdout => stdout_lines.push(line),
        OutputStream::Stderr => stderr_lines.push(line),
    }
}

#[derive(Clone, Copy)]
enum OutputStream {
    Stdout,
    Stderr,
}

fn spawn_output_reader<R>(
    stream: OutputStream,
    reader: R,
    tx: mpsc::Sender<(OutputStream, String)>,
) -> thread::JoinHandle<()>
where
    R: Read + Send + 'static,
{
    thread::spawn(move || {
        let mut reader = BufReader::new(reader);
        let mut buffer = Vec::new();
        loop {
            buffer.clear();
            match reader.read_until(b'\n', &mut buffer) {
                Ok(0) => break,
                Ok(_) => {
                    let text = String::from_utf8_lossy(&buffer)
                        .trim_end_matches(|ch| matches!(ch, '\r' | '\n'))
                        .to_string();
                    if tx.send((stream, text)).is_err() {
                        break;
                    }
                }
                Err(error) => {
                    let _ = tx.send((stream, format!("failed to read pip output: {error}")));
                    break;
                }
            }
        }
    })
}

fn runtime_home<R: Runtime>(app: &impl Manager<R>) -> RuntimeResult<PathBuf> {
    let app_data =
        prepare_runtime_directory(&app.path().app_data_dir()?, "application data directory")?;
    prepare_runtime_directory(&app_data.join("runtime"), "runtime state directory")
}

struct InstallLock {
    file: fs::File,
    lock_path: PathBuf,
    runtime_home: PathBuf,
    runtime_home_identity: fs::File,
}

impl InstallLock {
    fn require_current_identity(&self) -> RuntimeResult<()> {
        let current_runtime_home = open_directory_without_links(&self.runtime_home)?;
        let current_lock = open_regular_file_without_links(&self.lock_path)?;
        if !files_have_same_identity(&self.runtime_home_identity, &current_runtime_home)?
            || !files_have_same_identity(&self.file, &current_lock)?
        {
            return Err(format!(
                "runtime install lock path changed identity: {}",
                self.lock_path.display()
            )
            .into());
        }
        Ok(())
    }
}

impl Drop for InstallLock {
    fn drop(&mut self) {
        let _ = unlock_install_file(&self.file);
    }
}

fn acquire_install_lock(runtime_home: &Path) -> RuntimeResult<InstallLock> {
    let runtime_home = prepare_runtime_directory(runtime_home, "runtime state directory")?;
    let runtime_home_identity = open_directory_without_links(&runtime_home)?;
    let lock_path = runtime_home.join("install.lock");
    let mut file = open_install_lock_file(&lock_path).map_err(|error| {
        format!(
            "runtime install lock must be a regular non-link file ({}): {error}",
            lock_path.display()
        )
    })?;
    try_lock_install_file(&file).map_err(|error| {
        format!(
            "another Shinsekai runtime install appears to be running ({}): {error}",
            lock_path.display()
        )
    })?;
    file.set_len(0)?;
    file.seek(SeekFrom::Start(0))?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    writeln!(file, "pid={}", std::process::id())?;
    writeln!(file, "created_at_ms={now}")?;
    file.sync_data()?;
    let lock = InstallLock {
        file,
        lock_path,
        runtime_home,
        runtime_home_identity,
    };
    lock.require_current_identity()?;
    Ok(lock)
}

fn open_install_lock_file(lock_path: &Path) -> std::io::Result<fs::File> {
    if !path_has_no_link_components(lock_path) {
        return Err(std::io::Error::other(
            "path contains a symbolic link or reparse point",
        ));
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
        options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let file = options.open(lock_path)?;
    let metadata = file.metadata()?;
    if metadata_is_link(&metadata)
        || !metadata.file_type().is_file()
        || !path_has_no_link_components(lock_path)
    {
        return Err(std::io::Error::other(
            "path changed to a non-regular or linked file",
        ));
    }
    let verification = open_regular_file_without_links(lock_path)?;
    if !files_have_same_identity(&file, &verification)? {
        return Err(std::io::Error::other(
            "path changed to a different regular file",
        ));
    }
    Ok(file)
}

#[cfg(unix)]
fn try_lock_install_file(file: &fs::File) -> std::io::Result<()> {
    use std::os::fd::AsRawFd;

    let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if result == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(unix)]
fn unlock_install_file(file: &fs::File) -> std::io::Result<()> {
    use std::os::fd::AsRawFd;

    let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_UN) };
    if result == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(windows)]
fn try_lock_install_file(file: &fs::File) -> std::io::Result<()> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::{
        Storage::FileSystem::{LockFileEx, LOCKFILE_EXCLUSIVE_LOCK, LOCKFILE_FAIL_IMMEDIATELY},
        System::IO::OVERLAPPED,
    };

    let mut overlapped = OVERLAPPED::default();
    let result = unsafe {
        LockFileEx(
            file.as_raw_handle(),
            LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY,
            0,
            u32::MAX,
            u32::MAX,
            &mut overlapped,
        )
    };
    if result != 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[cfg(windows)]
fn unlock_install_file(file: &fs::File) -> std::io::Result<()> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::{Storage::FileSystem::UnlockFileEx, System::IO::OVERLAPPED};

    let mut overlapped = OVERLAPPED::default();
    let result =
        unsafe { UnlockFileEx(file.as_raw_handle(), 0, u32::MAX, u32::MAX, &mut overlapped) };
    if result != 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeProgressPayload {
    phase: &'static str,
    candidate_id: Option<String>,
    source: Option<String>,
    downloaded: Option<u64>,
    total: Option<u64>,
    speed_bytes_per_sec: Option<f64>,
    message: Option<String>,
    log_line: Option<String>,
}

fn emit_runtime_progress<R: Runtime, M: Manager<R> + Emitter<R>>(
    app: &M,
    phase: &'static str,
    candidate_id: Option<String>,
    source: Option<String>,
    downloaded: Option<u64>,
    total: Option<u64>,
    speed_bytes_per_sec: Option<f64>,
    message: Option<&str>,
    log_line: Option<&str>,
) {
    let _ = app.emit(
        RUNTIME_PROGRESS_EVENT,
        RuntimeProgressPayload {
            phase,
            candidate_id,
            source,
            downloaded,
            total,
            speed_bytes_per_sec,
            message: message.map(ToString::to_string),
            log_line: log_line.map(ToString::to_string),
        },
    );
}

fn requirements_path(source_root: &Path, requirements_file: &str) -> PathBuf {
    let path = PathBuf::from(requirements_file);
    if path.is_absolute() {
        path
    } else {
        source_root.join(path)
    }
}

fn prepare_runtime_directory(path: &Path, field: &str) -> RuntimeResult<PathBuf> {
    if !path.is_absolute() || path_is_filesystem_root(path) || !path_text_is_portable(path) {
        return Err(format!(
            "{field} must be an absolute, portable, non-root path: {}",
            path.display()
        )
        .into());
    }
    if !path_has_no_link_components(path) {
        return Err(format!(
            "{field} must not contain a symbolic link or reparse-point component: {}",
            path.display()
        )
        .into());
    }
    let mut missing_components = Vec::new();
    let mut existing_ancestor = path;
    loop {
        match fs::symlink_metadata(existing_ancestor) {
            Ok(metadata) => {
                if metadata_is_link(&metadata) || !metadata.is_dir() {
                    return Err(format!(
                        "{field} ancestor must be a real directory: {}",
                        existing_ancestor.display()
                    )
                    .into());
                }
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let name = existing_ancestor.file_name().ok_or_else(|| {
                    format!(
                        "{field} has no existing directory ancestor: {}",
                        path.display()
                    )
                })?;
                missing_components.push(name.to_owned());
                existing_ancestor = existing_ancestor.parent().ok_or_else(|| {
                    format!(
                        "{field} has no existing directory ancestor: {}",
                        path.display()
                    )
                })?;
            }
            Err(error) => return Err(error.into()),
        }
    }

    let mut current_path = existing_ancestor.to_path_buf();
    let mut current_identity = open_directory_without_links(&current_path)?;
    for component in missing_components.iter().rev() {
        require_open_directory_identity(
            &current_path,
            &current_identity,
            &format!("{field} parent"),
        )?;
        let next = current_path.join(component);
        match fs::create_dir(&next) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error.into()),
        }
        require_open_directory_identity(
            &current_path,
            &current_identity,
            &format!("{field} parent"),
        )?;
        current_identity = open_directory_without_links(&next)?;
        current_path = next;
    }
    require_open_directory_identity(path, &current_identity, field)?;
    Ok(path.to_path_buf())
}

fn safe_component(value: &str) -> String {
    let component = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.') {
                ch
            } else {
                '-'
            }
        })
        .collect::<String>();
    let trimmed = component.trim_matches(|ch| matches!(ch, '-' | '.'));
    if trimmed.is_empty() {
        "runtime".to_string()
    } else {
        trimmed.to_string()
    }
}

#[cfg(test)]
mod tests;
