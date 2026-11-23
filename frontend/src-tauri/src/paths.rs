use std::{
    env,
    path::{Path, PathBuf},
};

use tauri::Manager;

use crate::{
    project_root,
    state::{DesktopResult, RESTART_DEBUG_LOG_FILE},
};

pub(crate) fn resolve_source_root(app: &tauri::App) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_SOURCE_ROOT") {
        if has_bridge(&root) {
            return Ok(root);
        }
        return Err(format!(
            "SHINSEKAI_SOURCE_ROOT does not contain frontend_bridge.py: {}",
            root.display()
        )
        .into());
    }

    #[cfg(debug_assertions)]
    if let Some(root) = dev_project_root() {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        if has_bridge(&resource_dir) {
            return Ok(resource_dir);
        }
    }

    if let Some(root) = dev_project_root() {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    let exe_dir = env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    if let Some(root) = exe_dir {
        if has_bridge(&root) {
            return Ok(root);
        }
    }

    Err("could not locate Shinsekai application resources; set SHINSEKAI_SOURCE_ROOT".into())
}

pub(crate) fn resolve_project_root(
    app: &tauri::App,
    source_root: &Path,
    app_root: &Path,
) -> DesktopResult<project_root::ResolvedProjectRoot> {
    let app_config_dir = app.path().app_config_dir()?;
    let app_data_dir = app.path().app_data_dir()?;
    let config_dir = app.path().config_dir()?;
    let data_dir = app.path().data_dir()?;
    let locator_path = app_config_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE);

    let expanded_env = |name: &str| {
        env::var_os(name)
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .map(ExpandHome::expand_home)
            .map(PathBuf::into_os_string)
    };
    let explicit_root = project_root::preferred_environment_root(
        expanded_env("SHINSEKAI_PROJECT_ROOT"),
        expanded_env("EASYAI_PROJECT_ROOT"),
    );

    let legacy_config_dir = config_dir.join(project_root::LEGACY_APP_IDENTIFIER);
    let legacy_data_dir = data_dir.join(project_root::LEGACY_APP_IDENTIFIER);
    let current_data_dir = data_dir.join(project_root::CURRENT_APP_IDENTIFIER);
    let mut restart_log_paths = vec![env::temp_dir().join(RESTART_DEBUG_LOG_FILE)];
    if let Some(custom_log) = env::var_os("SHINSEKAI_RESTART_LOG")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
    {
        restart_log_paths.insert(0, custom_log);
    }

    let options = project_root::ProjectRootResolveOptions {
        explicit_root,
        source_root: source_root.to_path_buf(),
        app_root: app_root.to_path_buf(),
        current_app_data_project_root: app_data_dir.join("project"),
        legacy_app_data_project_roots: vec![legacy_data_dir.join("project")],
        locator_path,
        locator_read_paths: vec![
            app_data_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
            current_data_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
            legacy_config_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
            legacy_data_dir.join(project_root::PROJECT_ROOT_LOCATOR_FILE),
        ],
        restart_log_paths,
        untrusted_candidate_roots: project_root::windows_legacy_install_dir_hints(),
        development_source: app_root == source_root
            && dev_project_root().as_deref() == Some(source_root),
    };
    project_root::resolve(options).map_err(Into::into)
}

pub(crate) fn resolve_app_root(app: &tauri::App, source_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(root) = env_path("SHINSEKAI_APP_ROOT") {
        if root.is_dir() {
            return Ok(root);
        }
        return Err(format!("SHINSEKAI_APP_ROOT is not a directory: {}", root.display()).into());
    }

    if let Some(root) = appimage_app_root() {
        return Ok(root);
    }

    if dev_project_root().as_deref() == Some(source_root) {
        return Ok(source_root.to_path_buf());
    }

    if let Some(root) = app_root_from_current_exe() {
        return Ok(root);
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        if let Some(root) = app_root_from_resource_dir(&resource_dir) {
            return Ok(root);
        }
    }

    Ok(source_root.to_path_buf())
}

fn appimage_app_root() -> Option<PathBuf> {
    env_path("APPIMAGE")
        .and_then(|path| path.parent().map(Path::to_path_buf))
        .filter(|path| path.is_dir())
}

fn app_root_from_current_exe() -> Option<PathBuf> {
    env::current_exe()
        .ok()
        .and_then(|path| app_root_from_executable(&path))
}

pub(crate) fn app_root_from_executable(executable: &Path) -> Option<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        if let Some(app_bundle) = executable.ancestors().find(|ancestor| {
            ancestor
                .extension()
                .and_then(|extension| extension.to_str())
                .is_some_and(|extension| extension.eq_ignore_ascii_case("app"))
        }) {
            return app_bundle.parent().map(Path::to_path_buf);
        }
    }

    executable.parent().map(Path::to_path_buf)
}

pub(crate) fn app_root_from_resource_dir(resource_dir: &Path) -> Option<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        if let Some(app_bundle) = resource_dir.ancestors().find(|ancestor| {
            ancestor
                .extension()
                .and_then(|extension| extension.to_str())
                .is_some_and(|extension| extension.eq_ignore_ascii_case("app"))
        }) {
            return app_bundle.parent().map(Path::to_path_buf);
        }
    }

    if resource_dir.file_name().and_then(|name| name.to_str()) == Some("resources") {
        return resource_dir.parent().map(Path::to_path_buf);
    }
    Some(resource_dir.to_path_buf())
}

fn dev_project_root() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent()?.parent().map(Path::to_path_buf)
}

fn has_bridge(root: &Path) -> bool {
    root.join("frontend_bridge.py").is_file()
}

pub(crate) fn resolve_frontend_dist(project_root: &Path) -> DesktopResult<PathBuf> {
    if let Some(dist) = env_path("SHINSEKAI_FRONTEND_DIST") {
        if dist.join("index.html").is_file() {
            return Ok(dist);
        }
        return Err(format!(
            "SHINSEKAI_FRONTEND_DIST does not contain index.html: {}",
            dist.display()
        )
        .into());
    }

    let dist = project_root.join("frontend").join("dist");
    if dist.join("index.html").is_file() {
        return Ok(dist);
    }

    Err(format!(
        "built frontend not found at {}; run `pnpm build` in frontend first",
        dist.display()
    )
    .into())
}

fn env_path(name: &str) -> Option<PathBuf> {
    env::var_os(name)
        .map(PathBuf::from)
        .map(|path| path.expand_home())
        .map(|path| path.canonicalize().unwrap_or(path))
}

trait ExpandHome {
    fn expand_home(self) -> Self;
}

impl ExpandHome for PathBuf {
    fn expand_home(self) -> Self {
        let raw = self.as_os_str().to_string_lossy();
        if raw == "~" {
            return home_dir().unwrap_or(self);
        }
        if let Some(rest) = raw.strip_prefix("~/") {
            if let Some(home) = home_dir() {
                return home.join(rest);
            }
        }
        self
    }
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
