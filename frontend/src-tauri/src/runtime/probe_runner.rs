use std::{
    path::Path,
    process::{Command, Output},
    thread,
    time::Duration,
};

use serde::de::DeserializeOwned;

use super::python_env;

const PROBE_RETRY_DELAYS_MS: [u64; 2] = [150, 300];

#[derive(Debug)]
#[allow(dead_code)]
pub(super) struct RuntimeCheckReport {
    pub(super) ok: bool,
    pub(super) python_ok: bool,
    pub(super) bridge_ok: bool,
    pub(super) missing_imports: Vec<String>,
    pub(super) missing_distributions: Vec<String>,
    pub(super) stderr: String,
    pub(super) stdout: String,
    pub(super) message: String,
}

impl RuntimeCheckReport {
    pub(super) fn ok() -> Self {
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

pub(super) fn run_probe_command_with_retry<F>(
    command: &mut Command,
    should_retry_output: F,
) -> std::io::Result<Output>
where
    F: Fn(&Output) -> bool,
{
    run_probe_with_retry_using(
        || command.output(),
        |delay_ms| thread::sleep(Duration::from_millis(delay_ms)),
        &PROBE_RETRY_DELAYS_MS,
        should_retry_output,
    )
}

fn run_probe_with_retry_using<R, S, F>(
    mut run: R,
    mut sleep: S,
    delays_ms: &[u64],
    should_retry_output: F,
) -> std::io::Result<Output>
where
    R: FnMut() -> std::io::Result<Output>,
    S: FnMut(u64),
    F: Fn(&Output) -> bool,
{
    let mut attempt = 0;
    loop {
        let result = run();
        let can_retry = attempt < delays_ms.len();
        let retry = match &result {
            Ok(output) => can_retry && should_retry_output(output),
            Err(_) => can_retry,
        };
        if !retry {
            return result;
        }
        sleep(delays_ms[attempt]);
        attempt += 1;
    }
}

pub(super) fn check_python_imports(python: &Path, imports: &[String]) -> RuntimeCheckReport {
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
    let output = run_probe_command_with_retry(&mut command, |output| {
        let stdout = String::from_utf8_lossy(&output.stdout);
        match parse_json_line::<serde_json::Value>(&stdout) {
            Ok(value) => value
                .get("missing_imports")
                .and_then(|item| item.as_array())
                .is_none(),
            Err(_) => true,
        }
    });
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

pub(super) fn check_bridge_runtime(
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
        .arg("--requirements-only")
        .arg("--profile")
        .arg(profile)
        .arg("--project-root")
        .arg(source_root)
        .arg("--requirements-file")
        .arg(&requirements)
        .current_dir(source_root);
    python_env::configure_python_command(&mut command, python);
    let output = run_probe_command_with_retry(&mut command, |output| {
        !output.status.success()
            && parse_json_line::<serde_json::Value>(&String::from_utf8_lossy(&output.stdout))
                .is_err()
    });
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
    let parsed = parse_json_line::<serde_json::Value>(stdout);
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

pub(super) fn parse_bridge_check_output(stdout: &str, stderr: &str) -> (Vec<String>, String) {
    if let Ok(value) = parse_json_line::<serde_json::Value>(stdout) {
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

pub(super) fn parse_json_line<T: DeserializeOwned>(text: &str) -> Result<T, serde_json::Error> {
    let trimmed = text.trim();
    if trimmed.starts_with('{') {
        if let Ok(parsed) = serde_json::from_str::<T>(trimmed) {
            return Ok(parsed);
        }
    }
    if let Some(json_line) = trimmed
        .lines()
        .rev()
        .map(str::trim)
        .find(|line| line.starts_with('{') && line.ends_with('}'))
    {
        return serde_json::from_str(json_line);
    }
    serde_json::from_str(trimmed)
}

#[cfg(test)]
mod tests {
    use std::io;
    use std::process::{ExitStatus, Output};

    use serde::Deserialize;

    use super::{parse_json_line, run_probe_with_retry_using, PROBE_RETRY_DELAYS_MS};

    #[cfg(windows)]
    fn exit_status(code: u32) -> ExitStatus {
        use std::os::windows::process::ExitStatusExt;
        ExitStatus::from_raw(code)
    }

    #[cfg(unix)]
    fn exit_status(code: u32) -> ExitStatus {
        use std::os::unix::process::ExitStatusExt;
        ExitStatus::from_raw((code as i32) << 8)
    }

    fn fake_output(code: u32, stdout: &str) -> Output {
        Output {
            status: exit_status(code),
            stdout: stdout.as_bytes().to_vec(),
            stderr: Vec::new(),
        }
    }

    #[test]
    fn parse_json_line_ignores_noisy_preamble_lines() {
        #[derive(Debug, Deserialize, PartialEq)]
        struct ProbeSample {
            version: String,
        }

        let noisy = concat!(
            "pygame 2.6.1 (SDL 2.28.4, Python 3.10.18)\n",
            "Hello from the pygame community. https://www.pygame.org/contribute.html\n",
            "{\"version\": \"3.10.18\"}\n",
        );
        let parsed = parse_json_line::<ProbeSample>(noisy).unwrap();
        assert_eq!(
            parsed,
            ProbeSample {
                version: "3.10.18".to_string()
            }
        );
    }

    #[test]
    fn retry_recovers_after_transient_spawn_or_garbled_output_failures() {
        let mut attempts = 0;
        let mut sleeps = Vec::new();
        let output = run_probe_with_retry_using(
            || {
                attempts += 1;
                match attempts {
                    1 => Err(io::Error::new(io::ErrorKind::PermissionDenied, "locked")),
                    2 => Ok(fake_output(1, "truncated output")),
                    _ => Ok(fake_output(0, "{\"ok\":true}")),
                }
            },
            |delay| sleeps.push(delay),
            &PROBE_RETRY_DELAYS_MS,
            |output| {
                !output.status.success()
                    && parse_json_line::<serde_json::Value>(&String::from_utf8_lossy(&output.stdout))
                        .is_err()
            },
        )
        .unwrap();

        assert!(output.status.success());
        assert_eq!(attempts, 3);
        assert_eq!(sleeps, vec![150, 300]);
    }

    #[test]
    fn retry_does_not_repeat_when_structured_failure_report_is_returned() {
        let mut attempts = 0;
        let mut sleeps = Vec::new();
        let output = run_probe_with_retry_using(
            || {
                attempts += 1;
                Ok(fake_output(
                    1,
                    "{\"missingDistributions\":[\"pypdf\"],\"message\":\"missing pypdf\"}",
                ))
            },
            |delay| sleeps.push(delay),
            &PROBE_RETRY_DELAYS_MS,
            |output| {
                !output.status.success()
                    && parse_json_line::<serde_json::Value>(&String::from_utf8_lossy(&output.stdout))
                        .is_err()
            },
        )
        .unwrap();

        assert!(!output.status.success());
        assert_eq!(attempts, 1);
        assert!(sleeps.is_empty());
    }
}
