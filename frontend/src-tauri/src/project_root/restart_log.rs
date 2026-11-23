use std::{
    fs,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};

use super::ProjectRootCandidateSource;

const MAX_RESTART_LOG_BYTES: usize = 2 * 1024 * 1024;
pub(super) const MAX_RESTART_LOG_CANDIDATES: usize = 16;

pub(super) fn restart_log_candidates(
    log_path: &Path,
) -> Vec<(PathBuf, ProjectRootCandidateSource)> {
    let Ok(mut file) = fs::File::open(log_path) else {
        return Vec::new();
    };
    let Ok(length) = file.metadata().map(|metadata| metadata.len()) else {
        return Vec::new();
    };
    let start = length.saturating_sub(MAX_RESTART_LOG_BYTES as u64);
    if file.seek(SeekFrom::Start(start)).is_err() {
        return Vec::new();
    }
    let mut bytes = Vec::with_capacity((length - start) as usize);
    if file
        .take(MAX_RESTART_LOG_BYTES as u64)
        .read_to_end(&mut bytes)
        .is_err()
    {
        return Vec::new();
    }
    let mut content = String::from_utf8_lossy(&bytes).as_ref().to_string();
    if start > 0 {
        let Some(first_newline) = content.find('\n') else {
            return Vec::new();
        };
        content.drain(..=first_newline);
    }
    let mut candidates = Vec::new();
    for line in content.lines().rev() {
        if candidates.len() >= MAX_RESTART_LOG_CANDIDATES {
            break;
        }
        let Some((_, desktop_event)) = line.split_once(" component=desktop ") else {
            continue;
        };
        let Some(resolved_fields) = desktop_event.strip_prefix("setup resolved ") else {
            continue;
        };
        if let Some(project_root) = setup_log_field(
            resolved_fields,
            "project_root",
            &["app_root", "frontend_dist", "bridge_port", "url"],
        ) {
            candidates.push((
                PathBuf::from(project_root),
                ProjectRootCandidateSource::RestartLogProjectRoot,
            ));
        }
        if let Some(app_root) = setup_log_field(
            resolved_fields,
            "app_root",
            &["frontend_dist", "bridge_port", "url"],
        ) {
            candidates.push((
                PathBuf::from(app_root),
                ProjectRootCandidateSource::RestartLogAppRoot,
            ));
        }
    }
    candidates
}

fn setup_log_field(line: &str, field: &str, following_fields: &[&str]) -> Option<String> {
    let marker = format!(" {field}=");
    let start = line.find(&marker)? + marker.len();
    let tail = &line[start..];
    let end = following_fields
        .iter()
        .filter_map(|following| tail.find(&format!(" {following}=")))
        .min()
        .unwrap_or(tail.len());
    let raw_value = &tail[..end];
    if raw_value
        .chars()
        .any(|character| matches!(character, '\0' | '\r' | '\n'))
    {
        return None;
    }
    let value = raw_value.trim_matches([' ', '\t']);
    (!value.is_empty()
        && !value
            .chars()
            .any(|character| matches!(character, '\0' | '\r' | '\n')))
    .then(|| value.to_string())
}
