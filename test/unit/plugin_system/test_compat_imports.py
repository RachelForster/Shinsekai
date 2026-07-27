from __future__ import annotations


def test_core_plugin_compatibility_imports_resolve_to_new_implementations() -> None:
    from core.plugins.github_bundle_update import (
        install_github_plugin_under_plugins as old_github_install,
    )
    from core.plugins.package_download import PluginPackageError as OldPackageError
    from core.plugins.pip_runner import run_pip_install as old_run_pip_install
    from core.plugins.plugin_host import get_plugin_manager as old_get_plugin_manager
    from core.plugins.plugin_requirements_install import (
        install_plugin_requirements_txt as old_install_requirements,
    )
    from core.plugins.registry_catalog import RegistryPluginRecord as OldRegistryRecord
    from plugin_system.host import get_plugin_manager
    from plugin_system.install.package import PluginPackageError
    from plugin_system.registry.catalog import RegistryPluginRecord
    from plugin_system.requirements.install import install_plugin_requirements_txt
    from plugin_system.update.github import install_github_plugin_under_plugins
    from core.runtime_env.pip_runner import run_pip_install

    assert OldPackageError is PluginPackageError
    assert OldRegistryRecord is RegistryPluginRecord
    assert old_get_plugin_manager is get_plugin_manager
    assert old_github_install is install_github_plugin_under_plugins
    assert old_install_requirements is install_plugin_requirements_txt
    assert old_run_pip_install is run_pip_install
