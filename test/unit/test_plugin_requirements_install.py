from __future__ import annotations

from pathlib import Path


def test_finish_install_result_refreshes_plugin_target_on_success(monkeypatch):
    from core.plugins import plugin_requirements_install as installer

    calls: list[bool] = []
    monkeypatch.setattr(
        installer,
        "ensure_plugin_site_packages_on_syspath",
        lambda: calls.append(True),
    )

    result = installer._finish_install_result(("pip_ok", ""), Path("plugin_site_packages"))

    assert result == ("pip_ok", "")
    assert calls == [True]


def test_finish_install_result_does_not_refresh_on_failed_install(monkeypatch):
    from core.plugins import plugin_requirements_install as installer

    calls: list[bool] = []
    monkeypatch.setattr(
        installer,
        "ensure_plugin_site_packages_on_syspath",
        lambda: calls.append(True),
    )

    result = installer._finish_install_result(
        ("pip_failed", "boom"),
        Path("plugin_site_packages"),
    )

    assert result == ("pip_failed", "boom")
    assert calls == []
