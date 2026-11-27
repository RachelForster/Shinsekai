"""Tests for side-effect-free ``@builtin_adapter`` discovery across all AI domains."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import textwrap

import pytest

from ai.asr.registry import create_asr_adapter_registry, get_asr_adapter_registry
from ai.llm.registry import create_llm_adapter_registry, get_llm_adapter_registry
from ai.t2i.registry import create_t2i_adapter_registry, get_t2i_adapter_registry
from ai.tts.registry import create_tts_adapter_registry, get_tts_adapter_registry
from ai.vision.registry import create_vision_adapter_registry, get_vision_adapter_registry
from core.adapters import (
    AdapterRegistry,
    builtin_adapter,
    discover_builtin_adapters,
    get_builtin_adapter_specs,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _make_temp_pkg(tmp_path: Path, pkg_name: str, files: dict[str, str], monkeypatch) -> str:
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    for filename, content in files.items():
        (pkg_dir / filename).write_text(textwrap.dedent(content), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in list(sys.modules):
        if name == pkg_name or name.startswith(f"{pkg_name}."):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    return pkg_name


def test_drop_in_module_auto_discovered_without_touching_registry(
    tmp_path: Path, monkeypatch
) -> None:
    pkg_name = _make_temp_pkg(
        tmp_path,
        "tmp_dropin_adapters",
        {
            "_internal.py": """
                from core.adapters import builtin_adapter

                @builtin_adapter("ignored", order=1)
                class _Private:
                    pass
            """,
            "alpha.py": """
                from core.adapters import builtin_adapter

                @builtin_adapter("first", label="First", order=10)
                @builtin_adapter("second", label="Second", order=20, default_kwargs={"flag": True})
                class AlphaAdapter:
                    def __init__(self, flag: bool = False) -> None:
                        self.flag = flag

                AliasAlpha = AlphaAdapter
            """,
            "beta.py": """
                from core.adapters import builtin_adapter
                from tmp_dropin_adapters.alpha import AlphaAdapter

                @builtin_adapter("sub", label="Sub", order=15)
                class BetaAdapter(AlphaAdapter):
                    pass

                def register_builtin_adapters(registry) -> None:
                    registry.register_builtin("hooked", BetaAdapter, label="Hooked", order=30)
            """,
        },
        monkeypatch,
    )

    registry = AdapterRegistry(
        "Demo",
        key_normalizer=lambda key: str(key or "").strip().lower(),
        builtin_registrar=lambda target: discover_builtin_adapters(pkg_name, target),
    )

    assert registry.keys() == ("first", "sub", "second", "hooked")
    sub = registry.create("sub")
    second = registry.create("second")
    assert sub.flag is False
    assert second.flag is True
    assert "ignored" not in registry

    # Adding a brand-new module later discovers it cleanly on a fresh registry instance.
    (tmp_path / pkg_name / "gamma.py").write_text(
        textwrap.dedent(
            """
            from core.adapters import builtin_adapter

            @builtin_adapter("gamma", label="Gamma", order=5)
            class GammaAdapter:
                pass
            """
        ),
        encoding="utf-8",
    )
    importlib.invalidate_caches()

    fresh = AdapterRegistry(
        "Demo",
        key_normalizer=lambda key: str(key or "").strip().lower(),
        builtin_registrar=lambda target: discover_builtin_adapters(pkg_name, target),
    )
    assert fresh.keys() == ("gamma", "first", "sub", "second", "hooked")


def test_builtin_adapter_does_not_leak_to_subclass_and_rejects_duplicates(
    tmp_path: Path, monkeypatch
) -> None:
    @builtin_adapter("parent", order=10)
    class _Parent:
        pass

    class _Child(_Parent):
        pass

    assert len(get_builtin_adapter_specs(_Parent)) == 1
    assert get_builtin_adapter_specs(_Child) == ()

    pkg_name = _make_temp_pkg(
        tmp_path,
        "tmp_dup_adapters",
        {
            "one.py": """
                from core.adapters import builtin_adapter

                @builtin_adapter("MyKey", order=10)
                class OneAdapter:
                    pass
            """,
            "two.py": """
                from core.adapters import builtin_adapter

                @builtin_adapter("mykey", order=20)
                class TwoAdapter:
                    pass
            """,
        },
        monkeypatch,
    )

    registry = AdapterRegistry("Dup", key_normalizer=lambda k: k.strip().lower())
    with pytest.raises(ValueError, match="Duplicate built-in Dup adapter key"):
        discover_builtin_adapters(pkg_name, registry)


def test_all_five_domains_auto_discover_expected_builtins() -> None:
    llm_reg = create_llm_adapter_registry(include_builtins=True)
    tts_reg = create_tts_adapter_registry(include_builtins=True)
    t2i_reg = create_t2i_adapter_registry(include_builtins=True)
    asr_reg = create_asr_adapter_registry(include_builtins=True)
    vision_reg = create_vision_adapter_registry(include_builtins=True)

    assert llm_reg.keys() == (
        "Deepseek",
        "ChatGPT",
        "Gemini",
        "Claude",
        "豆包",
        "通义千问",
        "Ollama",
    )
    assert tts_reg.keys() == (
        "genie-tts",
        "kaggle-gpt-sovits",
        "gpt-sovits",
        "qwen3-tts-gguf",
        "index-tts",
        "cosyvoice",
    )
    assert t2i_reg.keys() == ("comfyui", "stable diffusion")
    assert asr_reg.keys() == ("sherpa_onnx", "vosk")
    assert vision_reg.keys() == (
        "chatgpt",
        "claude",
        "deepseek",
        "doubao",
        "gemini",
        "moondream",
        "ollama",
        "qwen",
    )

    # Confirm the default registries share identical built-in sets.
    assert get_llm_adapter_registry().keys() == llm_reg.keys()
    assert get_tts_adapter_registry().keys() == tts_reg.keys()
    assert get_t2i_adapter_registry().keys() == t2i_reg.keys()
    assert get_asr_adapter_registry().keys() == asr_reg.keys()
    assert get_vision_adapter_registry().keys() == vision_reg.keys()


def test_discovered_adapter_modules_defer_heavy_vendor_sdk_imports() -> None:
    forbidden_top_level = {"openai", "anthropic", "vosk", "sherpa_onnx", "torch", "pyaudio"}
    for domain in ("llm", "tts", "t2i", "asr", "vision"):
        adapters_dir = REPO_ROOT / "ai" / domain / "adapters"
        for path in sorted(adapters_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.Import):
                    imported = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported = {node.module.split(".")[0]}
                else:
                    continue
                overlap = imported & forbidden_top_level
                assert not overlap, f"{path.relative_to(REPO_ROOT)} has heavy top-level import: {overlap}"
