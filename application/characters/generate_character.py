from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from weakref import WeakKeyDictionary

from ai.llm.llm_manager import LLMAdapterFactory, LLMManager


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
) -> GenerateCharacterResult:
    """Generate and persist a character setting through the configured LLM."""
    from config.character_ops import CHARACTER_MUTATION_LOCK, save_character_patch

    if not name:
        return GenerateCharacterResult("请选择或输入要生成的角色的名字！", setting)

    if characters is not None:
        from application.characters.management import _CatalogCharacterTarget

        target = _CatalogCharacterTarget(characters)
        character = characters.get_by_name(name)
        if character is None:
            character, _, _ = save_character_patch(
                target,
                {
                    "name": name,
                    "character_setting": setting,
                    "character_brief": "",
                },
            )
            _refresh_characters_if_supported(config_store)
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
                return GenerateCharacterResult(f"创建角色 {name} 失败。", setting)

    char_id = str(getattr(character, "id", "") or "").strip()

    setting = "无" if not setting else setting
    template = f"""
    你需要帮助用户写出{name}的角色设定，包括{name}的背景信息，性格特点，和语言习惯。输出plain text格式，不要使用markdown格式。
    将{name}的背景信息，性格特点，和语言习惯分段写，并且同一段内标号，不一定是3点，有可能比3点多。
    输出格式示例：
    {name}的背景信息：
    1.姓名和出处：
    2.外表：
    3.背景：
    4.经历：

    {name}的性格特点：
    1.
    2.
    3.

    {name}的语言习惯：
    1.
    2.
    """

    try:
        llm_provider, llm_model, llm_base_url, api_key = (
            config_store.get_llm_api_config()
        )
        if not llm_provider or not api_key or not llm_model:
            return GenerateCharacterResult(
                "LLM 配置不完整，请先设定大语言模型供应商、模型和 API Key。",
                setting,
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
            )
            runtime.config_signature = signature

        runtime.manager.set_user_template(template)
        generated = runtime.manager.chat(
            f"补充信息：{setting},请输出结果：",
            stream=False,
            response_format={"type": "text"},
            include_local_time=False,
        )
        with CHARACTER_MUTATION_LOCK:
            if target is not None:
                current = (target.get_by_id(char_id) if char_id else None) or target.get_by_name(name)
                target_name = current.name if current is not None else name
                character, _, _ = save_character_patch(
                    target,
                    {"name": target_name, "character_setting": generated},
                    target_id=char_id or None,
                )
                _refresh_characters_if_supported(config_store)
            else:
                latest = config_store.get_character_by_name(name) or character
                latest.character_setting = generated
                character = latest
                config_store.save_characters_config()

        from application.characters.generate_briefs import (
            CHARACTER_BRIEF_PROMPT,
            normalize_character_brief,
        )

        try:
            runtime.manager.set_user_template(CHARACTER_BRIEF_PROMPT)
            generated_brief = normalize_character_brief(
                runtime.manager.chat(
                    f"人物名称：{name}\n人物设定：\n{generated or '无详细设定'}",
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
                character.character_setting,
                str(getattr(character, "character_brief", "") or ""),
            )

        with CHARACTER_MUTATION_LOCK:
            if target is not None:
                current = (target.get_by_id(char_id) if char_id else None) or target.get_by_name(name)
                target_name = current.name if current is not None else name
                character, _, _ = save_character_patch(
                    target,
                    {"name": target_name, "character_brief": generated_brief},
                    target_id=char_id or None,
                )
                _refresh_characters_if_supported(config_store)
            else:
                latest = config_store.get_character_by_name(name) or character
                latest.character_brief = generated_brief
                character = latest
                config_store.save_characters_config()
        return GenerateCharacterResult(
            "输出成功",
            character.character_setting,
            character.character_brief,
        )
    except ImportError:
        return GenerateCharacterResult(
            "输出失败: LLM 模块依赖未找到 (LLMAdapterFactory, LLMManager)",
            setting,
            str(getattr(character, "character_brief", "") or ""),
        )
    except Exception as exc:
        return GenerateCharacterResult(
            f"输出失败:{exc}",
            setting,
            str(getattr(character, "character_brief", "") or ""),
        )
