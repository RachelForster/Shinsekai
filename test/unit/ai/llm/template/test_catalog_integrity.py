"""Integrity, parity, and specification tests for YAML PromptCatalog and Standalone sync."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from unittest.mock import patch

import pytest

from ai.llm.template import (
    I18nSection,
    PROMPT_CATALOG,
    PromptCatalog,
    PromptLanguagePolicy,
    PromptSpec,
    Section,
    TemplateContext,
)
from ai.llm.template.sync_standalone import (
    STANDALONE_LOCALES_PATH,
    build_standalone_locales_payload,
    sync_standalone_locales,
)
from sdk.lang import SUPPORTED_LANGS


REPO_ROOT = Path(__file__).resolve().parents[5]
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _extract_placeholders(template: str) -> set[str]:
    stripped = template.replace("{{", "").replace("}}", "")
    return set(PLACEHOLDER_RE.findall(stripped))


def test_all_locales_share_identical_domains_and_nonempty_keys() -> None:
    expected_domains = (
        "dialog",
        "extraction",
        "generation",
        "perception",
        "session",
        "story",
    )
    base_keys = PROMPT_CATALOG.keys("zh_CN")
    assert len(base_keys) >= 240

    for locale in SUPPORTED_LANGS:
        assert PROMPT_CATALOG.domains(locale) == expected_domains
        assert PROMPT_CATALOG.keys(locale) == base_keys
        for key in base_keys:
            raw = PROMPT_CATALOG.raw(key, locale=locale)
            assert isinstance(raw, str) and raw != "", f"Empty or missing {key} in {locale}"


def test_placeholder_variables_match_across_all_locales() -> None:
    for key in PROMPT_CATALOG.keys("zh_CN"):
        zh_vars = _extract_placeholders(PROMPT_CATALOG.raw(key, locale="zh_CN") or "")
        for locale in ("en", "ja"):
            loc_vars = _extract_placeholders(PROMPT_CATALOG.raw(key, locale=locale) or "")
            assert loc_vars == zh_vars, (
                f"Placeholder mismatch for {key!r} between zh_CN ({zh_vars}) and {locale} ({loc_vars})"
            )


@pytest.mark.parametrize("locale", SUPPORTED_LANGS)
def test_dialog_catalog_preserves_byte_for_byte_parity_with_legacy_i18n_bundle(
    locale: str,
) -> None:
    legacy_path = REPO_ROOT / "i18n" / "locales" / f"{locale}.json"
    legacy_template_gen = json.loads(legacy_path.read_text(encoding="utf-8"))["template_gen"]
    assert len(legacy_template_gen) == 78

    for short_key, expected_text in legacy_template_gen.items():
        actual_text = PROMPT_CATALOG.translate(
            f"dialog.{short_key}",
            locale=locale,
            strict=True,
        )
        assert actual_text == expected_text, f"Parity drift in {locale} dialog.{short_key}"


def test_standalone_generated_locales_json_is_in_sync_with_yaml_catalog() -> None:
    assert STANDALONE_LOCALES_PATH.is_file()
    assert sync_standalone_locales(check=True) is True
    disk_payload = json.loads(STANDALONE_LOCALES_PATH.read_text(encoding="utf-8"))
    assert disk_payload == build_standalone_locales_payload(PROMPT_CATALOG)


def test_catalog_preserves_raw_json_braces_on_zero_arg_lookups() -> None:
    for locale in SUPPORTED_LANGS:
        head = PROMPT_CATALOG.translate("dialog.json_head_top", locale=locale)
        assert '"dialog": [' in head
        fallback = PROMPT_CATALOG.translate(
            "session.standalone_fallback_system_prompt",
            locale=locale,
        )
        assert '{ "dialog": [...] }' in fallback


def test_i18n_section_and_prompt_spec_follow_ui_and_locked_contract_policies(
    tmp_path: Path,
) -> None:
    for loc, greeting, schema_note in (
        ("zh_CN", "你好，{user}！", "中文契约"),
        ("en", "Hello, {user}!", "English contract"),
        ("ja", "こんにちは、{user}！", "日本語契約"),
    ):
        loc_dir = tmp_path / loc
        loc_dir.mkdir(parents=True)
        (loc_dir / "demo.yaml").write_text(
            f'greet: "{greeting}"\ncontract: "{schema_note}"\n',
            encoding="utf-8",
        )

    catalog = PromptCatalog(tmp_path)

    def build_follow_section() -> Section[TemplateContext]:
        return I18nSection(
            "greet",
            key="demo.greet",
            params=lambda _ctx: {"user": "Mika"},
        )

    def build_locked_section() -> Section[TemplateContext]:
        return I18nSection("contract", key="demo.contract")

    follow_spec = PromptSpec(
        id="demo.follow",
        language_policy=PromptLanguagePolicy.FOLLOW_UI,
        system_builder=build_follow_section,
    )
    locked_spec = PromptSpec(
        id="demo.locked",
        language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
        locked_locale="en",
        system_builder=build_locked_section,
    )

    assert (
        follow_spec.render_system(
            TemplateContext(locale="ja", translator=catalog.translator("ja"))
        )
        == "こんにちは、Mika！"
    )

    with patch("ai.llm.template.core.catalog.PROMPT_CATALOG", catalog):
        assert follow_spec.render_system(TemplateContext(locale="zh_CN")) == "你好，Mika！"
        assert follow_spec.render_system(TemplateContext(locale="en")) == "Hello, Mika!"
        assert follow_spec.render_system(TemplateContext(locale="ja")) == "こんにちは、Mika！"
        assert locked_spec.render_system(TemplateContext(locale="zh_CN")) == "English contract"
        assert locked_spec.render_system(TemplateContext(locale="ja")) == "English contract"


def test_pure_template_packages_do_not_import_runtime_or_application_layers() -> None:
    template_root = REPO_ROOT / "ai" / "llm" / "template"
    strict_pure_packages = (
        "core",
        "extraction",
        "generation",
        "perception",
        "prompts",
        "session",
        "story",
    )
    strict_forbidden = {"application", "config", "core", "frontend_bridge_core"}

    for pkg in (*strict_pure_packages, "dialog"):
        pkg_dir = template_root / pkg
        assert pkg_dir.is_dir(), f"Expected pure template package {pkg_dir}"
        forbidden_roots = (
            {"application", "frontend_bridge_core"}
            if pkg == "dialog"
            else strict_forbidden
        )
        for py_path in sorted(pkg_dir.rglob("*.py")):
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    modules = [node.module or ""]
                offending = [
                    mod for mod in modules if mod.partition(".")[0] in forbidden_roots
                ]
                assert not offending, (
                    f"Pure template module {py_path.relative_to(REPO_ROOT)} imported forbidden roots {offending}"
                )


def _walk_module_eager_nodes(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return []
    out = [node]
    for child in ast.iter_child_nodes(node):
        out.extend(_walk_module_eager_nodes(child))
    return out


def test_template_modules_never_call_render_at_module_import_time() -> None:
    template_root = REPO_ROOT / "ai" / "llm" / "template"
    offenders: list[str] = []
    for py_path in sorted(template_root.rglob("*.py")):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        for stmt in tree.body:
            for node in _walk_module_eager_nodes(stmt):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"render", "render_system", "render_user"}
                ):
                    offenders.append(f"{py_path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, (
        f"Static module-level prompt rendering freezes locale at import time: {offenders}"
    )
