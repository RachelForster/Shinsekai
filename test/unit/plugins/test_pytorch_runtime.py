from __future__ import annotations

from core.plugins.pytorch_runtime import (
    build_pytorch_install_plan,
    partition_pytorch_requirement_lines,
    pytorch_wheel_base_url,
    pytorch_wheel_index_url_for_cuda_version,
)


def _satisfied(line: str, installed: dict[str, str]) -> bool:
    from packaging.requirements import Requirement

    requirement = Requirement(line)
    version = installed.get(requirement.name.lower())
    return version is not None and requirement.specifier.contains(
        version,
        prereleases=True,
    )


def test_partition_pytorch_requirement_lines_keeps_stack_together():
    pytorch, other = partition_pytorch_requirement_lines(
        [
            "torch==2.7.1",
            "torchvision==0.22.1",
            "torchaudio==2.7.1",
            "transformers<5",
        ]
    )

    assert pytorch == [
        "torch==2.7.1",
        "torchvision==0.22.1",
        "torchaudio==2.7.1",
    ]
    assert other == ["transformers<5"]


def test_cuda_12_8_and_newer_selects_cu128():
    assert (
        pytorch_wheel_index_url_for_cuda_version(
            (13, 2),
            base_url="https://download.pytorch.org/whl",
        )[0]
        == "https://download.pytorch.org/whl/cu128"
    )
    assert (
        pytorch_wheel_index_url_for_cuda_version(
            (12, 8),
            base_url="https://download.pytorch.org/whl",
        )[0]
        == "https://download.pytorch.org/whl/cu128"
    )


def test_pytorch_wheel_base_follows_region_and_selected_pip_index(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_PYTORCH_WHEEL_BASE", raising=False)
    monkeypatch.delenv("SHINSEKAI_RUNTIME_SOURCE", raising=False)
    monkeypatch.delenv("SHINSEKAI_MIRROR_REGION", raising=False)

    assert (
        pytorch_wheel_base_url(["https://pypi.tuna.tsinghua.edu.cn/simple/"])
        == "https://mirrors.aliyun.com/pytorch-wheels"
    )
    assert (
        pytorch_wheel_base_url(["https://pypi.org/simple/"])
        == "https://download.pytorch.org/whl"
    )

    monkeypatch.setenv("SHINSEKAI_MIRROR_REGION", "china")
    assert (
        pytorch_wheel_base_url(["https://pypi.org/simple/"])
        == "https://mirrors.aliyun.com/pytorch-wheels"
    )
    monkeypatch.setenv("SHINSEKAI_MIRROR_REGION", "global")
    assert (
        pytorch_wheel_base_url(["https://pypi.tuna.tsinghua.edu.cn/simple/"])
        == "https://download.pytorch.org/whl"
    )


def test_pytorch_wheel_base_explicit_override_wins(monkeypatch):
    monkeypatch.setenv(
        "SHINSEKAI_PYTORCH_WHEEL_BASE",
        "https://mirror.example/pytorch/",
    )
    monkeypatch.setenv("SHINSEKAI_MIRROR_REGION", "china")

    assert (
        pytorch_wheel_base_url(["https://pypi.org/simple/"])
        == "https://mirror.example/pytorch"
    )


def test_matching_versions_and_cuda_build_skip_install():
    lines = [
        "torch==2.7.1",
        "torchvision==0.22.1",
        "torchaudio==2.7.1",
    ]
    installed = {
        "torch": "2.7.1+cu128",
        "torchvision": "0.22.1+cu128",
        "torchaudio": "2.7.1+cu128",
    }

    plan = build_pytorch_install_plan(
        lines,
        installed,
        requirement_is_satisfied=_satisfied,
        index_url="https://download.pytorch.org/whl/cu128",
    )

    assert plan.install_required is False
    assert plan.force_reinstall is False


def test_cpu_build_on_cuda_machine_forces_complete_reinstall():
    lines = [
        "torch==2.7.1",
        "torchvision==0.22.1",
        "torchaudio==2.7.1",
    ]
    installed = {
        "torch": "2.7.1+cpu",
        "torchvision": "0.22.1+cpu",
        "torchaudio": "2.7.1+cpu",
    }

    plan = build_pytorch_install_plan(
        lines,
        installed,
        requirement_is_satisfied=_satisfied,
        index_url="https://download.pytorch.org/whl/cu128",
    )

    assert plan.install_required is True
    assert plan.force_reinstall is True
    assert "expected cu128 wheels" in plan.detail


def test_broad_requirement_still_rejects_wrong_wheel_channel():
    plan = build_pytorch_install_plan(
        ["torch>=2.1.0"],
        {"torch": "2.12.1+cpu"},
        requirement_is_satisfied=_satisfied,
        index_url="https://download.pytorch.org/whl/cu128",
    )

    assert plan.install_required is True
    assert plan.force_reinstall is True
    assert "expected cu128 wheels" in plan.detail


def test_changed_versions_force_reinstall_even_on_matching_channel():
    lines = [
        "torch==2.7.1",
        "torchvision==0.22.1",
        "torchaudio==2.7.1",
    ]
    installed = {
        "torch": "2.11.0+cu128",
        "torchvision": "0.26.0+cu128",
        "torchaudio": "2.11.0+cu128",
    }

    plan = build_pytorch_install_plan(
        lines,
        installed,
        requirement_is_satisfied=_satisfied,
        index_url="https://download.pytorch.org/whl/cu128",
    )

    assert plan.install_required is True
    assert plan.force_reinstall is True
    assert "versions do not match" in plan.detail


def test_empty_environment_uses_normal_install():
    plan = build_pytorch_install_plan(
        ["torch==2.7.1", "torchaudio==2.7.1"],
        {},
        requirement_is_satisfied=_satisfied,
        index_url="https://download.pytorch.org/whl/cpu",
    )

    assert plan.install_required is True
    assert plan.force_reinstall is False
    assert "missing packages" in plan.detail
