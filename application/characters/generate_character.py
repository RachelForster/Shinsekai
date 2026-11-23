from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from weakref import WeakKeyDictionary

from ai.llm.llm_manager import LLMAdapterFactory, LLMManager
from ai.llm.template.generation.character_brief import (
    render_character_brief_prompts,
    render_character_setting_prompts,
)
from ai.llm.template.integrations.localization import (
    LocaleInput,
    resolve_dynamic_locale,
)


@dataclass
class _GenerationRuntime:
    manager: Any | None = None
    config_signature: tuple[tuple[str, str], ...] | None = None


_RUNTIMES: WeakKeyDictionary[Any, _GenerationRuntime] = WeakKeyDictionary()


@dataclass(frozen=True, slots=True)
class GenerateCharacterResult:
    message: str
    character_setting: str
    character_brief: str = ""
    ok: bool = True


class CharacterCreator(Protocol):
    """Character persistence capability required when the target is missing."""

    def add_character(self, **values: Any) -> Any: ...


class CharacterConfigStore(Protocol):
    """Narrow configuration surface used by character generation."""

    def get_character_by_name(self, name: str) -> Any | None: ...

    def get_llm_api_config(self) -> tuple[str, str, str, str]: ...

    def merged_llm_factory_kwargs(
        self, provider: str, base_kwargs: dict[str, Any]
    ) -> dict[str, Any]: ...

    def save_characters_config(self) -> None: ...


def _runtime_for(character_manager: Any) -> _GenerationRuntime:
    runtime = _RUNTIMES.get(character_manager)
    if runtime is None:
        runtime = _GenerationRuntime()
        _RUNTIMES[character_manager] = runtime
    return runtime


def _refresh_characters_if_supported(config_store: Any) -> None:
    refresh = getattr(config_store, "refresh_characters", None)
    if callable(refresh):
        refresh()


def generate_character(
    character_creator: CharacterCreator,
    config_store: CharacterConfigStore,
    name: str,
    setting: str,
    *,
    characters: Any = None,
    locale: LocaleInput = None,
) -> GenerateCharacterResult:
    """Generate and persist a character setting through the configured LLM."""
    from config.character_ops import CHARACTER_MUTATION_LOCK, save_character_patch

    if not name:
        return GenerateCharacterResult(
            "请选择或输入要生成的角色的名字！", setting, ok=False
        )

    if characters is not None:
        from application.characters.management import _CatalogCharacterTarget

        target = _CatalogCharacterTarget(characters)
        character = characters.get_by_name(name)
    else:
        target = None
        character = config_store.get_character_by_name(name)
        if character is None:
            with CHARACTER_MUTATION_LOCK:
                character = config_store.get_character_by_name(name)
                if character is None:
                    character_creator.add_character(
                        name=name,
                        color="",
                        sprite_prefix="",
                        gpt_model_path="",
                        sovits_model_path="",
                        refer_audio_path="",
                        prompt_text="",
                        prompt_lang="",
                        character_setting=setting,
                        character_brief="",
                    )
                    character = config_store.get_character_by_name(name)
            if character is None:
                return GenerateCharacterResult(
                    f"创建角色 {name} 失败。", setting, ok=False
                )

    char_id = str(getattr(character, "id", "") or "").strip()

    effective_locale = resolve_dynamic_locale(locale, config_manager=config_store)
    template, setting_user_prompt = render_character_setting_prompts(
        name,
        setting,
        locale=effective_locale,
    )

    try:
        llm_provider, llm_model, llm_base_url, api_key = (
            config_store.get_llm_api_config()
        )
        if not llm_provider or not api_key or not llm_model:
            return GenerateCharacterResult(
                "LLM 配置不完整，请先设定大语言模型供应商、模型和 API Key。",
                setting,
                str(getattr(character, "character_brief", "") or ""),
                ok=False,
            )

        factory_kwargs = config_store.merged_llm_factory_kwargs(
            llm_provider,
            {
                "llm_provider": llm_provider,
                "api_key": api_key,
                "base_url": llm_base_url,
                "model": llm_model,
            },
        )
        signature = tuple(
            sorted((str(key), repr(value)) for key, value in factory_kwargs.items())
        )
        runtime = _runtime_for(character_creator)
        if runtime.manager is None or runtime.config_signature != signature:
            adapter = LLMAdapterFactory.create_adapter(**factory_kwargs)
            runtime.manager = LLMManager(
                adapter=adapter,
                user_template=template,
                tools_enabled=False,
            )
            runtime.config_signature = signature
        elif hasattr(runtime.manager, "tools_enabled"):
            runtime.manager.tools_enabled = False

        runtime.manager.set_user_template(template)
        generated = str(
            runtime.manager.chat(
                setting_user_prompt,
                stream=False,
                response_format={"type": "text"},
                include_local_time=False,
            )
            or ""
        ).strip()
        if not generated:
            return GenerateCharacterResult(
                "输出失败:角色设定生成结果为空",
                setting,
                str(getattr(character, "character_brief", "") or ""),
                ok=False,
            )

        with CHARACTER_MUTATION_LOCK:
            if target is not None:
                if character is not None:
                    current = (
                        target.get_by_id(char_id) if char_id else None
                    ) or target.get_by_name(name)
                    if current is not None:
                        character, _, _ = save_character_patch(
                            target,
                            {"name": current.name, "character_setting": generated},
                            target_id=char_id or None,
                        )
                        _refresh_characters_if_supported(config_store)
            else:
                latest = config_store.get_character_by_name(name) or character
                latest.character_setting = generated
                character = latest
                config_store.save_characters_config()

        from application.characters.generate_briefs import normalize_character_brief

        try:
            brief_system, brief_user = render_character_brief_prompts(
                name,
                generated,
                locale=effective_locale,
            )
            runtime.manager.set_user_template(brief_system)
            generated_brief = normalize_character_brief(
                runtime.manager.chat(
                    brief_user,
                    stream=False,
                    response_format={"type": "text"},
                    include_local_time=False,
                )
            )
            if not generated_brief:
                raise ValueError("人物简介生成结果为空")
        except Exception as exc:
            return GenerateCharacterResult(
                f"角色设定输出成功，人物简介生成失败:{exc}",
                generated,
                str(getattr(character, "character_brief", "") or ""),
                ok=True,
            )

        with CHARACTER_MUTATION_LOCK:
            if target is not None:
                if character is not None:
                    current = (
                        target.get_by_id(char_id) if char_id else None
                    ) or target.get_by_name(name)
                    if current is not None:
                        character, _, _ = save_character_patch(
                            target,
                            {
                                "name": current.name,
                                "character_setting": generated,
                                "character_brief": generated_brief,
                            },
                            target_id=char_id or None,
                        )
                        _refresh_characters_if_supported(config_store)
            else:
                latest = config_store.get_character_by_name(name) or character
                latest.character_setting = generated
                latest.character_brief = generated_brief
                character = latest
                config_store.save_characters_config()
        return GenerateCharacterResult(
            "输出成功",
            generated,
            generated_brief,
            ok=True,
        )
    except ImportError:
        return GenerateCharacterResult(
            "输出失败: LLM 模块依赖未找到 (LLMAdapterFactory, LLMManager)",
            setting,
            str(getattr(character, "character_brief", "") or ""),
            ok=False,
        )
    except Exception as exc:
        return GenerateCharacterResult(
            f"输出失败:{exc}",
            setting,
            str(getattr(character, "character_brief", "") or ""),
            ok=False,
        )
